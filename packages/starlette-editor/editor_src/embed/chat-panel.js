/**
 * ChatPanel — floating AI chat panel for the Astraeus embed script.
 *
 * Sits bottom-left alongside the EditToolbar (bottom-right) and ChangesetPanel.
 * Opens a WebSocket chat session against /api/chat/sessions/{id}/ws and streams
 * tokens, tool events, and edit notices in real time.
 *
 * State machine::
 *   idle → thinking → streaming → (tool_calling | applying_edits)* → idle
 *
 * Usage::
 *   const panel = new ChatPanel(cmsBase, session, { getDocContext, apiKey })
 *   panel.mount()
 *   panel.toggle()
 */

const PANEL_STYLES = `
  position: fixed;
  bottom: 80px;
  left: 24px;
  z-index: 9998;
  width: 360px;
  max-height: 540px;
  background: #1e1e2e;
  color: #cdd6f4;
  border: 1px solid #313244;
  border-radius: 12px;
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 13px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.5);
  overflow: hidden;
  display: flex;
  flex-direction: column;
`

const BTN_BASE = `
  border: none;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  font-family: system-ui, -apple-system, sans-serif;
`

const BUBBLE_COMMON = `
  max-width: 85%;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.5;
  padding: 8px 12px;
`

export class ChatPanel {
  /**
   * @param {string} cmsBase
   * @param {object|null} session  - collab session reference (reserved for future use)
   * @param {{ getDocContext: () => object|null, apiKey?: string|null }} opts
   */
  constructor(cmsBase, session, { getDocContext, apiKey = null }) {
    this._base = cmsBase
    this._session = session
    this._getDocContext = getDocContext
    this._apiKey = apiKey
    this._sessionId = null
    this._ws = null
    this._state = 'idle'
    this._el = null
    this._messagesEl = null
    this._inputEl = null
    this._sendBtn = null
    this._currentAssistantBubble = null
    this._activeToolChips = {}   // tool_name → DOM element
    this._toolbar = null         // set by toolbar.setChatPanel()
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /** Append panel to document.body, initially hidden. */
  mount() {
    this._el = document.createElement('div')
    this._el.setAttribute('data-cms-chat-panel', '')
    this._el.style.cssText = PANEL_STYLES
    this._el.style.display = 'none'

    this._el.appendChild(this._buildHeader())
    this._messagesEl = this._buildMessagesArea()
    this._el.appendChild(this._messagesEl)

    const divider = document.createElement('div')
    divider.style.cssText = 'height: 1px; background: #313244; flex-shrink: 0;'
    this._el.appendChild(divider)

    this._el.appendChild(this._buildInputArea())

    document.body.appendChild(this._el)
  }

  /** Toggle panel visibility and reset unread badge via toolbar. */
  toggle() {
    if (!this._el) return
    const isVisible = this._el.style.display !== 'none'
    this._el.style.display = isVisible ? 'none' : 'flex'
    if (!isVisible) {
      // Opening — clear unread badge
      if (this._toolbar) {
        this._toolbar._unread = 0
        this._toolbar._updateChatBadge?.()
      }
    }
  }

  /** @returns {boolean} */
  get isOpen() {
    return this._el ? this._el.style.display !== 'none' : false
  }

  /**
   * Back-reference to the toolbar — set by toolbar.setChatPanel().
   * @param {import('./toolbar.js').EditToolbar} toolbar
   */
  setToolbar(toolbar) {
    this._toolbar = toolbar
  }

  // ── Sending ────────────────────────────────────────────────────────────────

  /**
   * Send a user message: append bubble, ensure session, set thinking state, send over WS.
   * @param {string} content
   */
  async send(content) {
    if (!content?.trim()) return
    this._appendMessage({ role: 'user', content })
    await this._ensureSession()
    this._setState('thinking')
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify({
        type: 'message',
        content,
        context: this._getDocContext?.() ?? null,
      }))
    }
    // Clear textarea (spec step 6 — also clears when called directly, not just from _sendFromInput)
    if (this._inputEl) {
      this._inputEl.value = ''
      this._inputEl.style.height = 'auto'
    }
  }

  // ── Private — session management ───────────────────────────────────────────

  /** Lazy session initialisation — POST /api/chat/sessions then open WS. */
  async _ensureSession() {
    if (this._sessionId) return
    const res = await fetch(`${this._base}/api/chat/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...this._authHeaders() },
      body: JSON.stringify({
        persona: 'default',
        doc_id: this._getDocContext?.()?.doc_id ?? null,
      }),
    })
    const { session_id } = await res.json()
    this._sessionId = session_id
    this._initWs(session_id)
  }

  /**
   * Open the chat WebSocket. Called once per session.
   * On close: sets this._ws = null so next send triggers a reconnect via _ensureSession.
   * @param {string} sessionId
   */
  _initWs(sessionId) {
    const wsBase = this._base.replace(/^https?/, match => match === 'https' ? 'wss' : 'ws')
    const url = this._apiKey
      ? `${wsBase}/api/chat/sessions/${sessionId}/ws?api_key=${this._apiKey}`
      : `${wsBase}/api/chat/sessions/${sessionId}/ws`

    this._ws = new WebSocket(url)

    this._ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        this._onServerMessage(msg)
      } catch {
        // Ignore malformed messages
      }
    }

    this._ws.onclose = () => {
      this._ws = null
    }

    this._ws.onerror = () => {
      if (this._ws) this._ws.close()
    }
  }

  /**
   * @returns {{ Authorization: string }|{}}
   */
  _authHeaders() {
    return this._apiKey ? { 'Authorization': 'Bearer ' + this._apiKey } : {}
  }

  // ── Private — server message routing ──────────────────────────────────────

  /**
   * Route an incoming server message through the state machine.
   * @param {{ type: string, [key: string]: any }} msg
   */
  _onServerMessage(msg) {
    switch (msg.type) {
      case 'thinking':
        this._setState('thinking')
        this._startAssistantBubble()
        break
      case 'token':
        this._setState('streaming')
        this._appendToken(msg.delta)
        // Notify toolbar of new message when panel is closed (unread badge)
        if (!this.isOpen && this._toolbar) {
          this._toolbar._onChatMessage?.()
        }
        break
      case 'tool_use':
        this._setState('tool_calling')
        this._appendToolChip(msg.tool, msg.input)
        break
      case 'tool_result':
        this._updateToolChip(msg.tool, msg.summary)
        break
      case 'applying_edits':
        this._setState('applying_edits')
        this._appendEditNotice(msg)
        break
      case 'done':
        this._setState('idle')
        this._finalizeAssistantBubble()
        break
    }
  }

  // ── Private — state machine ────────────────────────────────────────────────

  /**
   * Update internal state and reflect in input/send-button enabled state.
   * Shows/hides the "◆ thinking..." indicator.
   * @param {'idle'|'thinking'|'streaming'|'tool_calling'|'applying_edits'} state
   */
  _setState(state) {
    this._state = state
    const busy = state !== 'idle'

    if (this._inputEl) {
      this._inputEl.disabled = busy
      this._inputEl.style.opacity = busy ? '0.5' : '1'
    }
    if (this._sendBtn) {
      this._sendBtn.disabled = busy
      this._sendBtn.style.opacity = busy ? '0.5' : '1'
    }

    // Show thinking indicator in the stream area when state is 'thinking'
    if (state === 'thinking') {
      this._messagesEl?.querySelectorAll('[data-thinking]').forEach(el => el.remove())
      const indicator = document.createElement('div')
      indicator.setAttribute('data-thinking', '')
      indicator.style.cssText = `
        color: #6c7086;
        font-style: italic;
        font-size: 12px;
        padding: 4px 0;
        align-self: flex-start;
      `
      indicator.textContent = '◆ thinking...'
      this._messagesEl?.appendChild(indicator)
      this._scrollToBottom()
    } else {
      this._messagesEl?.querySelectorAll('[data-thinking]').forEach(el => el.remove())
    }
  }

  // ── Private — message rendering ────────────────────────────────────────────

  /**
   * Append a fully-formed message bubble (user or assistant).
   * @param {{ role: 'user'|'assistant', content: string }} opts
   */
  _appendMessage({ role, content }) {
    if (!this._messagesEl) return
    const bubble = document.createElement('div')

    if (role === 'user') {
      bubble.style.cssText = `
        ${BUBBLE_COMMON}
        align-self: flex-end;
        background: #89b4fa;
        color: #1e1e2e;
        border-radius: 12px 12px 2px 12px;
      `
    } else {
      bubble.style.cssText = `
        ${BUBBLE_COMMON}
        align-self: flex-start;
        background: #313244;
        color: #cdd6f4;
        border-radius: 2px 12px 12px 12px;
      `
    }

    bubble.textContent = content
    this._messagesEl.appendChild(bubble)
    this._scrollToBottom()
  }

  /** Start a new streaming assistant bubble. Stores ref in _currentAssistantBubble. */
  _startAssistantBubble() {
    if (!this._messagesEl) return
    const bubble = document.createElement('div')
    bubble.style.cssText = `
      ${BUBBLE_COMMON}
      align-self: flex-start;
      background: #313244;
      color: #cdd6f4;
      border-radius: 2px 12px 12px 12px;
    `
    this._messagesEl.appendChild(bubble)
    this._currentAssistantBubble = bubble
    this._scrollToBottom()
  }

  /**
   * Append a token delta to the active streaming assistant bubble.
   * If no bubble exists yet, starts one first.
   * @param {string} delta
   */
  _appendToken(delta) {
    if (!this._currentAssistantBubble) {
      this._startAssistantBubble()
    }
    this._currentAssistantBubble.textContent += delta
    this._scrollToBottom()
  }

  /**
   * Add a tool-use chip showing "🔍 tool_name { key: val... }".
   * @param {string} tool
   * @param {object} input
   */
  _appendToolChip(tool, input) {
    if (!this._messagesEl) return
    const chip = document.createElement('div')
    chip.style.cssText = `
      align-self: flex-start;
      background: #1e1e2e;
      border: 1px solid #45475a;
      color: #89b4fa;
      padding: 6px 10px;
      border-radius: 8px;
      font-size: 12px;
      font-family: monospace;
      max-width: 90%;
      word-break: break-all;
    `
    chip.textContent = `🔍 ${tool} ${this._summarizeInput(input)}`
    this._messagesEl.appendChild(chip)
    this._activeToolChips[tool] = chip
    this._scrollToBottom()
  }

  /**
   * Resolve a pending tool chip to "✓ result summary".
   * @param {string} tool
   * @param {string} summary
   */
  _updateToolChip(tool, summary) {
    const chip = this._activeToolChips[tool]
    if (!chip) return
    chip.style.color = '#a6e3a1'
    chip.textContent = `✓ ${summary}`
    delete this._activeToolChips[tool]
  }

  /**
   * Append an edit-notice row: "✏️ Applying N edits — rationale".
   * @param {{ step_count?: number, edit_rationale?: string }} msg
   */
  _appendEditNotice(msg) {
    if (!this._messagesEl) return
    const notice = document.createElement('div')
    notice.style.cssText = `
      align-self: stretch;
      background: #1e1e2e;
      border: 1px solid #89b4fa;
      color: #89b4fa;
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 12px;
      line-height: 1.5;
    `
    const count = msg.step_count ?? 0
    const rationale = msg.edit_rationale ?? ''
    notice.textContent = `✏️ Applying ${count} edit${count !== 1 ? 's' : ''} — ${rationale}`
    this._messagesEl.appendChild(notice)
    this._scrollToBottom()
  }

  /** Detach the current streaming bubble reference after 'done'. */
  _finalizeAssistantBubble() {
    this._currentAssistantBubble = null
  }

  // ── Private — utilities ────────────────────────────────────────────────────

  /**
   * Compact an input object to "{ key: val, ... }" (first 2 keys, truncated values).
   * @param {object} input
   * @returns {string}
   */
  _summarizeInput(input) {
    if (!input || typeof input !== 'object') return ''
    const entries = Object.entries(input).slice(0, 2)
    if (entries.length === 0) return '{}'
    const inner = entries
      .map(([k, v]) => `${k}: ${JSON.stringify(v).slice(0, 30)}`)
      .join(', ')
    return `{ ${inner} }`
  }

  _scrollToBottom() {
    if (this._messagesEl) {
      this._messagesEl.scrollTop = this._messagesEl.scrollHeight
    }
  }

  // ── Private — DOM construction ─────────────────────────────────────────────

  _buildHeader() {
    const header = document.createElement('div')
    header.style.cssText = `
      padding: 12px 14px 10px;
      border-bottom: 1px solid #313244;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    `

    const title = document.createElement('span')
    title.style.cssText = 'font-weight: 700; color: #cdd6f4;'
    title.textContent = '💬 Chat'

    const closeBtn = document.createElement('button')
    closeBtn.style.cssText = `${BTN_BASE} background: transparent; color: #6c7086; font-size: 16px; padding: 0 4px;`
    closeBtn.textContent = '×'
    closeBtn.addEventListener('click', () => this.toggle())

    header.appendChild(title)
    header.appendChild(closeBtn)
    return header
  }

  _buildMessagesArea() {
    const el = document.createElement('div')
    el.style.cssText = `
      flex: 1;
      overflow-y: auto;
      padding: 10px 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-height: 200px;
      max-height: 380px;
    `
    return el
  }

  _buildInputArea() {
    const inputArea = document.createElement('div')
    inputArea.style.cssText = `
      padding: 10px 14px;
      display: flex;
      gap: 8px;
      align-items: flex-end;
      flex-shrink: 0;
    `

    this._inputEl = document.createElement('textarea')
    this._inputEl.placeholder = 'Ask Claude...'
    this._inputEl.rows = 1
    this._inputEl.style.cssText = `
      flex: 1;
      background: #313244;
      color: #cdd6f4;
      border: 1px solid #45475a;
      border-radius: 8px;
      padding: 8px 10px;
      font-size: 13px;
      font-family: system-ui, -apple-system, sans-serif;
      resize: none;
      min-height: 36px;
      max-height: 96px;
      overflow-y: auto;
      line-height: 1.4;
    `

    // Auto-resize up to 4 lines (~96px)
    this._inputEl.addEventListener('input', () => {
      this._inputEl.style.height = 'auto'
      this._inputEl.style.height = Math.min(this._inputEl.scrollHeight, 96) + 'px'
    })

    // Send on Enter; Shift+Enter inserts newline
    this._inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        this._sendFromInput()
      }
    })

    this._sendBtn = document.createElement('button')
    this._sendBtn.textContent = 'Send'
    this._sendBtn.style.cssText = `
      ${BTN_BASE}
      background: #89b4fa;
      color: #1e1e2e;
      padding: 8px 14px;
      font-weight: 600;
    `
    this._sendBtn.addEventListener('click', () => this._sendFromInput())

    inputArea.appendChild(this._inputEl)
    inputArea.appendChild(this._sendBtn)
    return inputArea
  }

  _sendFromInput() {
    const content = this._inputEl?.value?.trim()
    if (!content) return
    this.send(content)
    // Textarea clearing is handled by send()
  }
}
