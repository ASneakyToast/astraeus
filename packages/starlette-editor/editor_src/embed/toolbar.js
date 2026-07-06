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
export class EditToolbar {
  constructor({ cmsBase, cmsElements, reloadUrl = null }) {
    this.cmsBase = cmsBase
    this.cmsElements = cmsElements  // all [data-cms-id] elements on page
    this.reloadUrl = reloadUrl      // optional dev-server reload endpoint
    this.state = 'viewing'          // 'viewing' | 'editing' | 'saving' | 'publishing' | 'published'
    this.activeElement = null       // currently-editing [data-cms-id] element
    this.el = null                  // the toolbar DOM element
    this.changesetPanel = null      // set externally by index.js after ChangesetPanel is created
    this._chatPanel = null          // set via setChatPanel()
    this._chatBtn = null            // ref to the 💬 button for badge updates
    this._unread = 0                // unread chat message count
  }

  mount() {
    this.el = document.createElement('div')
    this.el.id = 'astraeus-toolbar'
    this.el.style.cssText = `
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
      font-family: system-ui, sans-serif;
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
      const saveIndicator = this._makeIndicator(
        this.state === 'saving' ? '⏳ Saving...' : '✓ Saved'
      )
      const discardBtn = this._makeButton('Discard draft', 'ghost', () => this._discardDraft())
      const publishBtn = this._makeButton('Publish', 'success', () => this._publish())
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
      this.el.appendChild(this._makeIndicator('✓ Published — rebuilding site'))
    }
  }

  _makeButton(label, variant, onClick) {
    const btn = document.createElement('button')
    btn.textContent = label
    const styles = {
      primary: 'background:#2563eb;color:#fff;border:none;',
      success: 'background:#16a34a;color:#fff;border:none;',
      ghost: 'background:rgba(255,255,255,0.1);color:#fff;border:1px solid rgba(255,255,255,0.2);',
    }
    btn.style.cssText = `
      padding: 10px 18px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      backdrop-filter: blur(8px);
      ${styles[variant] || styles.primary}
    `
    btn.addEventListener('click', onClick)
    return btn
  }

  _makeIndicator(text) {
    const el = document.createElement('div')
    el.textContent = text
    el.style.cssText = `
      padding: 8px 14px;
      border-radius: 8px;
      background: rgba(0,0,0,0.7);
      color: #fff;
      font-size: 13px;
      backdrop-filter: blur(8px);
    `
    return el
  }

  setState(newState) {
    this.state = newState
    this._render()
  }

  async _startEditing() {
    // Import and activate edit mode for the first cms element
    // (multi-element selection is a future enhancement)
    const el = this.cmsElements[0]
    const { activateEditMode } = await import('./edit-mode.js')
    this.activeElement = el
    await activateEditMode(el, { cmsBase: this.cmsBase, toolbar: this })
    this.setState('editing')
  }

  async _discardDraft() {
    if (!this.activeElement) return
    const docId = this.activeElement.dataset.cmsId
    await fetch(`${this.cmsBase}/api/documents/${docId}/discard-draft`, {
      method: 'POST',
      credentials: 'include',
    })
    // Reload to get the published state
    window.location.reload()
  }

  async _publish() {
    if (!this.activeElement) return
    this.setState('publishing')
    const docId = this.activeElement.dataset.cmsId
    await fetch(`${this.cmsBase}/api/documents/${docId}/publish`, {
      method: 'POST',
      credentials: 'include',
    })
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
   * @param {import('./chat-panel.js').ChatPanel} chatPanel
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
