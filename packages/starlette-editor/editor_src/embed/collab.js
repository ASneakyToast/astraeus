/**
 * CollabConnection — manages the WebSocket connection to the CMS step authority.
 *
 * Implements the prosemirror-collab client protocol:
 *   - On connect: receives init with doc + version
 *   - On local edit: sends sendable steps to server
 *   - On server confirmation: receiveTransaction applied to local state
 *   - On reject: rebase pending steps against server version (reconnect)
 *   - Reconnects with exponential backoff on disconnect
 *
 * Protocol:
 *   Server → client init:   { type: 'init', doc: <PM JSON>, version: <int> }
 *   Client → server steps:  { type: 'steps', steps: [...], clientID, version, doc }
 *   Server → client steps:  { type: 'steps', steps: [...], clientIDs: [...], version }
 *   Server → client reject: { type: 'reject', version: <int> }
 *   Keep-alive:             { type: 'ping' } → { type: 'pong' }
 */
import { collab, sendableSteps, receiveTransaction, getVersion } from 'prosemirror-collab'
import { Step } from 'prosemirror-transform'

export { collab }

export class CollabConnection {
  constructor({ view, schema, documentId, cmsBase, initialVersion, toolbar, clientID }) {
    this.view = view              // EditorView instance
    this.schema = schema          // ProseMirror Schema
    this.documentId = documentId
    this.cmsBase = cmsBase
    this.version = initialVersion
    this.toolbar = toolbar
    this.clientID = clientID      // UUID identifying this client
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
    return `${base}/api/documents/${this.documentId}/collab`
  }

  _connect() {
    if (this._destroyed) return
    this.ws = new WebSocket(this._wsUrl())

    this.ws.onopen = () => {
      this._reconnectDelay = 1000  // reset backoff on successful connect
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

    this.ws.onclose = () => {
      clearInterval(this._pingInterval)
      this._pingInterval = null
      if (!this._destroyed) {
        // Exponential backoff reconnect
        setTimeout(() => this._connect(), this._reconnectDelay)
        this._reconnectDelay = Math.min(this._reconnectDelay * 2, 30000)
      }
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

    if (msg.type === 'init') {
      // Server sends current state — handles reconnects where we may have
      // missed steps. Update local version to match server.
      this.version = msg.version
      // Populate peer map from the server's current peer list
      this._peers = new Map()
      for (const p of (msg.peers ?? [])) {
        this._peers.set(p.client_id, p)
      }
      this._toolbar?.updatePeers(this._peers)
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
      // Apply confirmed steps from server
      const steps = msg.steps.map(s => Step.fromJSON(this.schema, s))
      const clientIDs = msg.clientIDs

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

    else if (msg.type === 'reject') {
      // Server rejected our steps — version mismatch.
      // Update local version. The simplest correct recovery is to reconnect:
      // server will send an 'init' with current state on connect.
      this.version = msg.version
      this.ws.close()
    }
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
    if (this.ws) this.ws.close()
  }
}
