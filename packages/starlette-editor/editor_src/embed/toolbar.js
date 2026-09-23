/**
 * EditToolbar — floating live-editing toolbar for the Astraeus embed script.
 *
 * States:
 *   viewing    — "✏️ Edit draft" button
 *   editing    — "✓ Saved" indicator + Discard + Publish
 *   saving     — "⏳ Saving..." indicator + Discard + Publish
 *   publishing — spinner
 *   published  — "✓ Published — rebuilding site"
 */
import { getActiveChangesetId, setActiveChangesetId } from '../changeset-store.js'

export class EditToolbar {
  constructor({ cmsBase, cmsElements, reloadUrl = null }) {
    this.cmsBase = cmsBase
    this.cmsElements = cmsElements  // all [data-cms-id] elements on page
    this.reloadUrl = reloadUrl      // optional dev-server reload endpoint
    this.state = 'viewing'          // 'viewing' | 'editing' | 'saving' | 'publishing' | 'published'
    this.activeElements = []        // every [data-cms-id] activated for editing
    this.el = null                  // the toolbar DOM element
    this.changesetPanel = null      // set externally by index.js after ChangesetPanel is created
    this._chatPanel = null          // set via setChatPanel()
    this._chatBtn = null            // ref to the 💬 button for badge updates
    this._unread = 0                // unread chat message count
    this._saveError = null          // message shown when a save/connection fails
  }

  mount() {
    this.el = document.createElement('div')
    this.el.id = 'astraeus-toolbar'
    // A solid dark pill, so the buttons sit on a consistent surface and stay
    // legible on any host background. (The old styling used white text on
    // translucent-white buttons — invisible on a light site.) Values are
    // literal, not the shared design tokens: injecting tokens.css would define
    // :root vars that collide with the host page's own tokens.
    this.el.style.cssText = `
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 2147483000;
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 6px;
      max-width: min(560px, calc(100vw - 48px));
      padding: 6px;
      background: #1a1a1a;
      border: 1px solid #2a2a2a;
      border-radius: 14px;
      box-shadow: 0 6px 24px rgba(0, 0, 0, 0.4);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
      padding-bottom: calc(6px + env(safe-area-inset-bottom));
    `
    document.body.appendChild(this.el)
    this._render()
  }

  _render() {
    // Clear and re-render toolbar content based on this.state
    this.el.innerHTML = ''

    if (this.state === 'viewing') {
      const btn = this._makeButton('✏️ Edit draft', 'primary', () => this._startEditing())
      this.el.appendChild(btn)
    }

    if (this.state === 'editing' || this.state === 'saving') {
      // Leave edit mode without discarding or publishing — the draft is kept.
      const closeBtn = this._makeButton('✕ Close', 'ghost', () => this._stopEditing())
      closeBtn.title = 'Stop editing — your draft is kept and can be resumed later'
      // A failed save takes over the indicator — the whole point is that it is
      // impossible to miss, unlike the silent failure this replaces.
      const saveIndicator = this._saveError
        ? this._makeIndicator(this._saveError, '#e04b45')
        : this._makeIndicator(this.state === 'saving' ? '⏳ Saving...' : '✓ Saved')
      const discardBtn = this._makeButton('Discard draft', 'danger', () => this._discardDraft())
      const publishBtn = this._makeButton('Publish', 'primary', () => this._publish())
      this.el.appendChild(closeBtn)
      this.el.appendChild(saveIndicator)
      this.el.appendChild(discardBtn)
      this.el.appendChild(publishBtn)
      if (this.changesetPanel) {
        const csBtn = this._makeButton('📋 Changesets', 'ghost', () => this.changesetPanel.toggle())
        this.el.appendChild(csBtn)
      }
      if (this._chatPanel) {
        this._chatBtn = this._makeButton('💬 Chat', 'ghost', () => {
          this._unread = 0
          this._updateChatBadge()
          this._chatPanel.toggle()
        })
        this.el.appendChild(this._chatBtn)
      }
    }

    if (this.state === 'publishing') {
      this.el.appendChild(this._makeIndicator('Publishing...'))
    }

    if (this.state === 'published') {
      this.el.appendChild(this._makeIndicator('✓ Published — site rebuilding (~30s)'))
    }
  }

  _makeButton(label, variant, onClick) {
    const btn = document.createElement('button')
    btn.textContent = label
    // On the dark pill: primary is filled light, ghost is outlined light,
    // danger carries the one accent hue (matches the tokenised palette).
    const styles = {
      primary: 'background:#f0f0f0;color:#0d0d0d;border:1px solid #f0f0f0;',
      ghost: 'background:transparent;color:#e8e8e8;border:1px solid #3a3a3a;',
      danger: 'background:transparent;color:#e04b45;border:1px solid rgba(224,75,69,0.5);',
    }
    btn.style.cssText = `
      padding: 8px 14px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 500;
      font-family: inherit;
      line-height: 1;
      white-space: nowrap;
      ${styles[variant] || styles.primary}
    `
    btn.addEventListener('click', onClick)
    return btn
  }

  _makeIndicator(text, color = '#a3a3a3') {
    const el = document.createElement('div')
    el.textContent = text
    // Sits directly on the pill — no separate background.
    el.style.cssText = `
      padding: 8px 10px;
      color: ${color};
      font-size: 13px;
      white-space: nowrap;
    `
    return el
  }

  /** Show a save/connection failure in the toolbar until the next success. */
  setSaveError(message) {
    this._saveError = message
    this._render()
  }

  /** Clear a previously shown save error (called after a successful save). */
  clearSaveError() {
    if (!this._saveError) return
    this._saveError = null
    this._render()
  }

  setState(newState) {
    this.state = newState
    this._render()
  }

  async _startEditing() {
    // Activate every annotated document on the page, so a listing edits as a
    // whole rather than only its first entry. Each edit joins one changeset
    // (see edit-mode patchField), so the session publishes together.
    const { activateEditMode, suppressAnchorNavigationWhileEditing } = await import('./edit-mode.js')
    // Listing cards wrap the title in the card's link; keep clicks-to-edit from
    // navigating away.
    suppressAnchorNavigationWhileEditing()
    this.activeElements = [...this.cmsElements]
    for (const el of this.activeElements) {
      await activateEditMode(el, { cmsBase: this.cmsBase, toolbar: this })
    }
    this.setState('editing')
  }

  _stopEditing() {
    // Leave edit mode while keeping the draft. The draft lives server-side and
    // the changeset id persists in changeset-store (localStorage), so
    // re-entering edit mode later resumes exactly where you left off. A reload
    // is the simplest reliable teardown of the in-page edit affordances
    // (contentEditable, ProseMirror mounts, dashed outlines, "Open" links) —
    // the same mechanism discard/publish already use, minus the mutation.
    window.location.reload()
  }

  async _discardDraft() {
    if (!this.activeElements.length) return
    // Discard every edited document's draft, not just one — the session
    // spanned all of them.
    await Promise.all(
      this.activeElements.map(el =>
        fetch(`${this.cmsBase}/api/documents/${el.dataset.cmsId}/discard-draft`, {
          method: 'POST',
          credentials: 'include',
        }),
      ),
    )
    // Reload to get the published state
    window.location.reload()
  }

  async _publish() {
    // A session's edits are grouped into one changeset — publish the whole
    // changeset so everything ships at once and fires a single rebuild.
    // Publish directly (not via the shell's Review & Publish drawer, whose
    // styles live in editor.css and aren't loaded on the host site).
    const changesetId = getActiveChangesetId()

    const url = changesetId
      ? `${this.cmsBase}/api/changesets/${changesetId}/publish`
      : this.activeElements[0]
        ? `${this.cmsBase}/api/documents/${this.activeElements[0].dataset.cmsId}/publish`
        : null
    if (!url) return

    if (!window.confirm('Publish your changes? The site will rebuild — it takes about 30 seconds to go live.')) {
      return
    }

    this.setState('publishing')
    let ok = false
    try {
      const res = await fetch(url, { method: 'POST', credentials: 'include' })
      ok = res.ok
    } catch { ok = false }

    if (!ok) {
      // Back to editing so the drafts aren't lost and they can retry.
      this.setState('editing')
      window.alert('Publish failed — your draft is safe. Please try again.')
      return
    }

    if (changesetId) setActiveChangesetId(null) // session shipped; start fresh
    this.setState('published')
    // In local dev, ping the Astro dev server to trigger a full-page reload
    if (this.reloadUrl) {
      try { await fetch(this.reloadUrl, { method: 'POST' }) } catch { /* ignore */ }
    }
  }

  // ── Chat panel wiring ──────────────────────────────────────────────────────

  /**
   * Wire a ChatPanel to the toolbar.
   * Also back-references the toolbar on the panel so it can call _onChatMessage().
   * Triggers a re-render so the 💬 button appears.
   * @param {import('../components/chat-panel.js').ChatPanel} chatPanel
   */
  setChatPanel(chatPanel) {
    this._chatPanel = chatPanel
    chatPanel.setToolbar(this)
    this._render()
  }

  /**
   * Called by ChatPanel when a 'token' event arrives while the panel is closed.
   * Increments the unread count and updates the badge on the 💬 button.
   */
  _onChatMessage() {
    if (!this._chatPanel?.isOpen) {
      this._unread = (this._unread || 0) + 1
      this._updateChatBadge()
    }
  }

  /**
   * Reflect the current unread count on the 💬 button label.
   */
  _updateChatBadge() {
    if (!this._chatBtn) return
    const count = this._unread || 0
    this._chatBtn.textContent = count > 0 ? `💬 Chat (${count})` : '💬 Chat'
  }

  // ── Peer presence ──────────────────────────────────────────────────────────

  /**
   * Rebuild the peer-presence strip from the current peers Map.
   * Inserts/updates a #astraeus-peer-presence container in the toolbar.
   *
   * @param {Map<string, {client_id: string, display: string, type?: string, client_type?: string}>} peersMap
   */
  updatePeers(peersMap) {
    // Inject CSS once
    if (!document.getElementById('astraeus-peer-styles')) {
      const style = document.createElement('style')
      style.id = 'astraeus-peer-styles'
      style.textContent = `
        .peer-indicator { font-size: 11px; margin: 0 3px; opacity: 0.85; }
        .peer-indicator.human { color: #a6e3a1; }
        .peer-indicator.ai { color: #cba6f7; }
        .peer-indicator.ai.pulsing { animation: ai-pulse 0.8s ease-in-out infinite; }
        @keyframes ai-pulse { 0%,100% { opacity: 0.85; } 50% { opacity: 0.3; } }
      `
      document.head.appendChild(style)
    }

    if (!this.el) return

    // Find or create the peer-presence container
    let peerSection = this.el.querySelector('#astraeus-peer-presence')
    if (!peerSection) {
      peerSection = document.createElement('div')
      peerSection.id = 'astraeus-peer-presence'
      peerSection.style.cssText = 'display:flex;flex-wrap:wrap;align-items:center;gap:2px;'
      this.el.appendChild(peerSection)
    }

    peerSection.innerHTML = ''
    for (const [clientId, peer] of peersMap) {
      const peerType = peer.type ?? peer.client_type ?? 'human'
      const span = document.createElement('span')
      span.className = `peer-indicator ${peerType}`
      span.dataset.clientId = clientId
      span.textContent = peerType === 'ai' ? `◆ ${peer.display}` : `● ${peer.display}`
      peerSection.appendChild(span)
    }
  }

  /**
   * Toggle the "pulsing" animation on an AI peer's indicator span.
   *
   * @param {string} clientId  The server-assigned client_id of the AI peer.
   * @param {boolean} isEditing  True to start pulsing; false to stop.
   */
  setAiEditing(clientId, isEditing) {
    const section = this.el?.querySelector('#astraeus-peer-presence')
    if (!section) return
    const span = section.querySelector(`[data-client-id="${clientId}"]`)
    if (!span) return
    if (isEditing) {
      span.classList.add('pulsing')
    } else {
      span.classList.remove('pulsing')
    }
  }
}
