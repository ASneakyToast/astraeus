/**
 * CollabConnection — manages the WebSocket connection to the CMS step authority.
 *
 * Implements the prosemirror-collab client protocol:
 *   - On connect: receives init with doc + version
 *   - On local edit: sends sendable steps to server
 *   - On server confirmation: receiveTransaction applied to local state
 *   - On reject: hold pending steps; they rebase when the broadcast arrives
 *   - Reconnects with exponential backoff on disconnect
 *
 * Protocol:
 *   Server → client init:   { type: 'init', doc: <PM JSON>, version: <int> }
 *   Client → server steps:  { type: 'steps', steps: [...], clientID, version, doc }
 *   Server → client steps:  { type: 'steps', steps: [...], clientIDs: [...], version }
 *   Server → client reject: { type: 'reject', version: <int>, reason?: string }
 *   Client → server catch-up: { type: 'catch_up', version } → { type: 'steps', ... } | { type: 'resync_required', doc, version }
 *   Keep-alive:             { type: 'ping' } → { type: 'pong' }
 */
import { collab, sendableSteps, receiveTransaction, getVersion } from 'prosemirror-collab'
import { Step } from 'prosemirror-transform'
import { getActiveChangesetId, setActiveChangesetId } from './changeset-store.js'
import { stateForServerCopy } from './collab-sync.js'

export { collab }

/** How long to wait for a `catch_up` reply before warning that it was not served. */
const CATCH_UP_TIMEOUT_MS = 5000

export class CollabConnection {
  constructor({ view, schema, documentId, field, cmsBase, initialVersion, toolbar, clientID, apiKey = null }) {
    this.view = view              // EditorView instance
    this.schema = schema          // ProseMirror Schema
    this.documentId = documentId
    this.field = field            // rich-text field being edited, e.g. 'body_markdown'
    this.cmsBase = cmsBase
    this.version = initialVersion
    this.toolbar = toolbar
    this.clientID = clientID      // UUID identifying this client
    this.apiKey = apiKey          // optional API key for shell (cookie auth not available)
    this.ws = null
    this._reconnectDelay = 1000   // ms, doubles on each failure (max 30000)
    this._destroyed = false
    this._pingInterval = null
    this._peers = new Map()       // server client_id → peer info dict
    this._toolbar = null          // set via setToolbar() for peer-presence updates
    this._connect()
  }

  /** Wire an EditToolbar for peer-presence display callbacks. */
  setToolbar(toolbar) {
    this._toolbar = toolbar
  }

  /** Current ProseMirror document as JSON, or null if no view. */
  currentDoc() {
    return this.view?.state.doc.toJSON() ?? null
  }

  /** Current collab version number from the local ProseMirror state. */
  currentVersion() {
    return getVersion(this.view?.state) ?? 0
  }

  /** Current selection range {from, to}, or null if no view. */
  currentSelection() {
    const sel = this.view?.state.selection
    return sel ? { from: sel.from, to: sel.to } : null
  }

  _wsUrl() {
    // Convert https://cms.example.com → wss://cms.example.com
    const base = this.cmsBase.replace(/^https?/, match => match === 'https' ? 'wss' : 'ws')
    // The server scopes the session to this field; without it an edit would
    // overwrite the whole document body, so it rejects field-less connections.
    const params = new URLSearchParams({ field: this.field })
    if (this.apiKey) params.set('api_key', this.apiKey)
    return `${base}/api/documents/${this.documentId}/collab?${params}`
  }

  _connect() {
    if (this._destroyed) return
    this.ws = new WebSocket(this._wsUrl())

    this.ws.onopen = () => {
      this._reconnectDelay = 1000  // reset backoff on successful connect
      this.toolbar?.clearSaveError?.()  // a prior connection error is resolved
      // Start ping interval
      this._pingInterval = setInterval(() => {
        if (this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, 30000)
    }

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      this._handleMessage(msg)
    }

    this.ws.onclose = (event) => {
      clearInterval(this._pingInterval)
      this._pingInterval = null
      if (this._destroyed) return
      // 4401 = auth rejected by the server. Reconnecting keeps failing, so stop
      // and surface it — the body-edit equivalent of a 401 on the PATCH path.
      if (event.code === 4401) {
        this.toolbar?.setSaveError?.('⚠ Body not saved — session expired, log in again')
        return
      }
      // Exponential backoff reconnect
      setTimeout(() => this._connect(), this._reconnectDelay)
      this._reconnectDelay = Math.min(this._reconnectDelay * 2, 30000)
    }

    this.ws.onerror = () => {
      this.ws.close()
    }
  }

  _handleMessage(msg) {
    if (msg.type === 'pong') {
      // Keep-alive response — no action needed
      return
    }

    if (msg.type === 'changeset') {
      // Server created a changeset to hold this body edit — adopt it so the rest
      // of the session (title/description PATCHes, other cards) groups into it.
      setActiveChangesetId(msg.id)
      return
    }

    if (msg.type === 'init') {
      // Server sends current state — handles reconnects where we may have
      // missed steps. Take its copy and version (see collab-sync.js): keeping
      // our own loaded copy let a stale editor overwrite the draft, and never
      // updating the collab plugin's version got every step rejected once the
      // server's version moved past 0.
      this.version = msg.version
      const synced = stateForServerCopy(this.view.state, {
        docJSON: msg.doc,
        version: msg.version,
        clientID: this.clientID,
        schema: this.schema,
      })
      if (synced) this.view.updateState(synced)
      // Populate peer map from the server's current peer list
      this._peers = new Map()
      for (const p of (msg.peers ?? [])) {
        this._peers.set(p.client_id, p)
      }
      this._toolbar?.updatePeers(this._peers)
      this._resumePendingSteps(msg.version)
    }

    else if (msg.type === 'peer_joined') {
      this._peers.set(msg.peer.client_id, msg.peer)
      this._toolbar?.updatePeers(this._peers)
    }

    else if (msg.type === 'peer_left') {
      this._peers.delete(msg.client_id)
      this._toolbar?.updatePeers(this._peers)
    }

    else if (msg.type === 'editing') {
      this._toolbar?.setAiEditing(msg.client_id, true)
    }

    else if (msg.type === 'editing_done') {
      this._toolbar?.setAiEditing(msg.client_id, false)
    }

    else if (msg.type === 'steps') {
      this._catchUpAnswered()
      // prosemirror-collab counts steps; it does not know which version a step
      // belongs to. A batch that does not start exactly at our version (one that
      // raced ahead of a catch-up, one we already have) would be applied to the
      // wrong document, so check before applying. `msg.version` is the version
      // *after* the batch.
      const localVersion = getVersion(this.view.state)
      const firstVersion = msg.version - msg.steps.length
      if (msg.version <= localVersion) return  // already have all of these
      if (firstVersion > localVersion) {
        // A gap: we missed steps (a broadcast raced our catch-up). Ask for them;
        // the reply starts at our version and includes this batch.
        this._requestCatchUp()
        return
      }
      const skip = localVersion - firstVersion  // overlap we already applied
      const steps = msg.steps.slice(skip).map(s => Step.fromJSON(this.schema, s))
      const clientIDs = msg.clientIDs.slice(skip)

      const tr = receiveTransaction(
        this.view.state,
        steps,
        clientIDs
      )
      this.view.dispatch(tr)
      this.version = msg.version

      // Show saved indicator after confirmation
      this.toolbar.setState('editing')

      // After receiving, check if we have pending local steps to send
      this._sendPendingSteps()
    }

    else if (msg.type === 'resync_required') {
      this._catchUpAnswered()
      // The server no longer has the steps between our version and its own, so
      // our pending steps cannot be rebased. Keep them and say so rather than
      // silently diverging or dropping them.
      console.warn(
        `[astraeus] Server version ${msg.version} is too far ahead of local edits ` +
        `(based on version ${getVersion(this.view.state)}) to catch up. They have not been saved.`,
      )
      this.toolbar?.setSaveError?.('⚠ Edits made while offline could not be merged — copy them out, then reload')
    }

    else if (msg.type === 'reject') {
      // Someone else's steps landed first, so ours were based on a stale
      // version. Our steps are still pending in the collab plugin: the server
      // broadcasts every accepted batch to all connections, and when that
      // broadcast arrives the 'steps' handler rebases through
      // receiveTransaction and retries the send.
      //
      // Closing the socket here used to strand them. Nothing resends after a
      // reconnect, so the edits stayed local — and the next keystroke sent them
      // at the same stale version, rejecting and reconnecting again.
      //
      // Not saved yet, so don't say so: this used to show "Saved", which hid
      // the version mismatch that dropped every body edit.
      this.version = msg.version
      this.toolbar.setState('saving')
    }
  }

  /**
   * Re-send anything left pending after a (re)connect.
   *
   * A brief drop — tunnel, wifi handoff — leaves the server where we left it,
   * so pending steps are still based on a document it recognises and can just
   * be sent.
   *
   * If the server moved on while we were away, our steps are based on a
   * document it no longer has. Rebasing needs the steps we missed, so ask for
   * them (`catch_up`, ADR 024). They come back as an ordinary `steps` message,
   * which the handler below applies with `receiveTransaction`, rebasing our
   * pending steps over them, and then resends what is left. A server that
   * cannot serve them answers `resync_required`; one that predates the message
   * ignores it, and the steps stay pending as before.
   *
   * @param {number} serverVersion
   */
  _resumePendingSteps(serverVersion) {
    if (!sendableSteps(this.view.state)) return

    const localVersion = getVersion(this.view.state)
    if (localVersion === serverVersion) {
      this._sendPendingSteps()
      return
    }

    this._requestCatchUp()
  }

  /**
   * Ask the server for the steps after our version (ADR 024).
   *
   * A server that predates `catch_up` ignores it, which would leave pending
   * edits unsaved without a word (they used to produce a warning). So if
   * nothing answers, say so.
   */
  _requestCatchUp() {
    if (this.ws?.readyState !== WebSocket.OPEN) return
    const version = getVersion(this.view.state)
    this.ws.send(JSON.stringify({ type: 'catch_up', version }))
    clearTimeout(this._catchUpTimer)
    this._catchUpTimer = setTimeout(() => {
      console.warn(
        `[astraeus] Asked the server for the steps after version ${version} and got no answer. ` +
        'Local edits based on that version cannot be rebased and have not been saved.',
      )
    }, CATCH_UP_TIMEOUT_MS)
  }

  _catchUpAnswered() {
    clearTimeout(this._catchUpTimer)
    this._catchUpTimer = null
  }

  _sendPendingSteps() {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return

    const sendable = sendableSteps(this.view.state)
    if (!sendable) return

    this.toolbar.setState('saving')

    this.ws.send(JSON.stringify({
      type: 'steps',
      steps: sendable.steps.map(s => s.toJSON()),
      clientID: this.clientID,
      version: sendable.version,
      doc: this.view.state.doc.toJSON(),  // include updated doc for server
      // Group this body edit into the session's changeset. The server links the
      // doc and, if it had to create a changeset, echoes it back (see below) so
      // plain-text edits join the same one.
      activeChangesetId: getActiveChangesetId(),
    }))
  }

  // Called by EditorView.dispatchTransaction after state update
  onTransaction() {
    this._sendPendingSteps()
  }

  destroy() {
    this._destroyed = true
    clearInterval(this._pingInterval)
    this._pingInterval = null
    this._catchUpAnswered()
    if (this.ws) this.ws.close()
  }
}
