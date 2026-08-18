// @vitest-environment happy-dom
/**
 * Tests for embed/chat-panel.js — ChatPanel logic and state machine.
 *
 * WebSocket is not natively available in happy-dom so we provide a mock.
 * DOM manipulation is tested via the panel's message area and state accessors.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ChatPanel } from '../embed/chat-panel.js'
import { EditToolbar } from '../embed/toolbar.js'

// ── Mock WebSocket ────────────────────────────────────────────────────────────

class MockWebSocket {
  constructor(url) {
    this.url = url
    this.readyState = MockWebSocket.OPEN
    this.sent = []
    MockWebSocket.instances.push(this)
    // Fire onopen on the next tick so _initWs()'s open-promise resolves
    // (handlers are assigned synchronously right after construction).
    setTimeout(() => this.onopen?.(), 0)
  }

  send(data) {
    this.sent.push(JSON.parse(data))
  }

  close() {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }

  // Helper: simulate a message arriving from the server
  _receive(data) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  static OPEN = 1
  static CLOSED = 3
  static instances = []
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function makePanel(opts = {}) {
  return new ChatPanel('http://cms.test', null, {
    getDocContext: () => ({
      doc_id: 'doc-1',
      version: 0,
      draft_body: null,
      selection: null,
    }),
    apiKey: opts.apiKey ?? 'test-key',
  })
}

function makeMountedPanel(opts = {}) {
  const panel = makePanel(opts)
  panel.mount()
  // Pre-wire a session and WS so tests don't need to go through _ensureSession()
  panel._sessionId = 'sess-1'
  panel._initWs('sess-1')
  return panel
}

function makeFetch(sessionId = 'sess-1') {
  return vi.fn(() =>
    Promise.resolve({ json: () => Promise.resolve({ session_id: sessionId }) })
  )
}

// ── Setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  MockWebSocket.instances = []
  global.WebSocket = MockWebSocket
})

afterEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('ChatPanel.mount() and toggle()', () => {
  it('mounts hidden (display none)', () => {
    const panel = makePanel()
    panel.mount()
    expect(panel._el.style.display).toBe('none')
  })

  it('toggle() makes the panel visible', () => {
    const panel = makePanel()
    panel.mount()
    panel.toggle()
    expect(panel._el.style.display).not.toBe('none')
  })

  it('toggle() twice hides it again', () => {
    const panel = makePanel()
    panel.mount()
    panel.toggle()
    panel.toggle()
    expect(panel._el.style.display).toBe('none')
  })

  it('isOpen reflects current visibility', () => {
    const panel = makePanel()
    panel.mount()
    expect(panel.isOpen).toBe(false)
    panel.toggle()
    expect(panel.isOpen).toBe(true)
  })

  it('mounts with messages area, textarea, and send button', () => {
    const panel = makePanel()
    panel.mount()
    expect(panel._messagesEl).toBeTruthy()
    expect(panel._inputEl).toBeTruthy()
    expect(panel._sendBtn).toBeTruthy()
  })
})

describe('ChatPanel — geometry persistence', () => {
  beforeEach(() => localStorage.clear())

  it('persists geometry to localStorage on drag/resize end', () => {
    const panel = makePanel()
    panel.mount()
    Object.assign(panel._el.style, { left: '40px', top: '60px', width: '400px', height: '320px' })

    panel._persistGeometry()

    const saved = JSON.parse(localStorage.getItem('cms-chat-panel-geometry'))
    expect(saved).toBeTruthy()
    expect(saved).toHaveProperty('left')
    expect(saved).toHaveProperty('width')
  })

  it('restores saved geometry on mount, clamped into the viewport', () => {
    localStorage.setItem(
      'cms-chat-panel-geometry',
      JSON.stringify({ left: 50, top: 70, width: 420, height: 300 }),
    )
    const panel = makePanel()
    panel.mount()

    expect(panel._el.style.width).toBe('420px')
    expect(panel._el.style.height).toBe('300px')
    expect(panel._el.style.left).toBe('50px')
    expect(panel._el.style.top).toBe('70px')
    // Switched to top/left anchoring
    expect(panel._el.style.bottom).toBe('auto')
  })
})

describe('ChatPanel.send()', () => {
  it('appends a user message bubble to the messages area', async () => {
    vi.stubGlobal('fetch', makeFetch())
    const panel = makePanel()
    panel.mount()

    await panel.send('Hello there')

    const bubbles = panel._messagesEl.children
    expect(bubbles.length).toBeGreaterThanOrEqual(1)
    // First child should be the user bubble
    const userBubble = Array.from(bubbles).find(el => el.textContent === 'Hello there')
    expect(userBubble).toBeTruthy()
  })

  it('does nothing for empty / whitespace-only content', async () => {
    vi.stubGlobal('fetch', makeFetch())
    const panel = makePanel()
    panel.mount()

    await panel.send('   ')

    expect(panel._messagesEl.children.length).toBe(0)
  })

  it('sets state to "thinking" and sends over WS', async () => {
    vi.stubGlobal('fetch', makeFetch())
    const panel = makePanel()
    panel.mount()

    await panel.send('Improve the intro')

    const ws = MockWebSocket.instances[0]
    expect(ws).toBeTruthy()
    const sentMsg = ws.sent.find(m => m.type === 'message')
    expect(sentMsg).toBeTruthy()
    expect(sentMsg.content).toBe('Improve the intro')
  })

  it('clears the textarea after send', async () => {
    vi.stubGlobal('fetch', makeFetch())
    const panel = makePanel()
    panel.mount()
    panel._inputEl.value = 'test message'

    await panel.send('test message')

    expect(panel._inputEl.value).toBe('')
  })
})

describe('ChatPanel._onServerMessage() — thinking', () => {
  it('shows the thinking indicator in the messages area', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'thinking' })

    const indicator = panel._messagesEl.querySelector('[data-thinking]')
    expect(indicator).toBeTruthy()
    expect(indicator.textContent).toContain('thinking')
    expect(indicator.textContent).toContain('◆')
  })

  it('removes the thinking indicator when transitioning to streaming', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'thinking' })
    panel._onServerMessage({ type: 'token', delta: 'Hi' })

    const indicator = panel._messagesEl.querySelector('[data-thinking]')
    expect(indicator).toBeNull()
  })

  it('disables input while thinking', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'thinking' })
    expect(panel._inputEl.disabled).toBe(true)
    expect(panel._sendBtn.disabled).toBe(true)
  })
})

describe('ChatPanel._onServerMessage() — token streaming', () => {
  it('builds a streaming assistant bubble from token deltas (raw buffer)', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'token', delta: 'Hello ' })
    panel._onServerMessage({ type: 'token', delta: 'world' })

    expect(panel._currentAssistantBubble).toBeTruthy()
    expect(panel._currentAssistantBubble._raw).toBe('Hello world')
  })

  it('sets state to "streaming"', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'token', delta: 'Hi' })
    expect(panel._state).toBe('streaming')
  })

  it('creates the bubble on first token even without a prior "thinking" event', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'token', delta: 'Sure' })
    expect(panel._currentAssistantBubble).toBeTruthy()
    expect(panel._currentAssistantBubble._raw).toBe('Sure')
  })

  it('renders markdown to HTML in the bubble (lists, emphasis)', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'token', delta: '- one\n' })
    panel._onServerMessage({ type: 'token', delta: '- two\n' })

    const html = panel._currentAssistantBubble.innerHTML
    expect(html).toContain('<ul>')
    expect(html).toContain('<li>one</li>')
    expect(html).toContain('<li>two</li>')
  })

  it('escapes raw HTML in LLM output (markdown-it html:false)', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'token', delta: '<img src=x onerror=alert(1)>' })

    const html = panel._currentAssistantBubble.innerHTML
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;img')
  })
})

describe('ChatPanel — per-turn bubble splitting', () => {
  it('starts a fresh bubble after a tool chip so each ReAct turn is separate', () => {
    const panel = makeMountedPanel()

    // Turn 1: assistant text
    panel._onServerMessage({ type: 'token', delta: 'Let me search.' })
    const firstBubble = panel._currentAssistantBubble
    expect(firstBubble._raw).toBe('Let me search.')

    // Tool call ends the turn
    panel._onServerMessage({ type: 'tool_use', tool: 'search_documents', input: { query: 'x' } })
    expect(panel._currentAssistantBubble).toBeNull()

    // Turn 2: new text → new bubble, not appended to the first
    panel._onServerMessage({ type: 'token', delta: 'Found it.' })
    expect(panel._currentAssistantBubble).not.toBe(firstBubble)
    expect(panel._currentAssistantBubble._raw).toBe('Found it.')
    expect(firstBubble._raw).toBe('Let me search.')
  })
})

describe('ChatPanel._onServerMessage() — tool_use / tool_result', () => {
  it('appends a chip with 🔍 and tool name on tool_use', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({
      type: 'tool_use',
      tool: 'search_documents',
      input: { query: 'test query' },
    })

    const chip = panel._activeToolChips['search_documents']
    expect(chip).toBeTruthy()
    expect(chip.textContent).toContain('🔍')
    expect(chip.textContent).toContain('search_documents')
  })

  it('resolves chip to "✓ tool — summary" on tool_result and removes from activeToolChips', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({
      type: 'tool_use',
      tool: 'search_documents',
      input: { query: 'test' },
    })
    panel._onServerMessage({
      type: 'tool_result',
      tool: 'search_documents',
      summary: 'Found 3 documents',
    })

    const chip = panel._messagesEl.querySelector('div[style*="monospace"]')
    expect(chip).toBeTruthy()
    expect(chip.textContent).toContain('✓')
    // Keeps the tool name alongside the summary
    expect(chip.textContent).toContain('search_documents')
    expect(chip.textContent).toContain('Found 3 documents')
    expect(chip.textContent).toContain('—')
    // Removed from activeToolChips after resolution
    expect(panel._activeToolChips['search_documents']).toBeUndefined()
  })

  it('falls back to "✓ tool" (no bare {}) when the summary is empty', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'tool_use', tool: 'create_document', input: {} })
    panel._onServerMessage({ type: 'tool_result', tool: 'create_document', summary: '' })

    const chip = panel._messagesEl.querySelector('div[style*="monospace"]')
    expect(chip.textContent).toContain('✓ create_document')
    expect(chip.textContent).not.toContain('{}')
    expect(chip.textContent).not.toContain('—')
  })

  it('renders an empty-input tool chip without a bare {}', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'tool_use', tool: 'list_types', input: {} })

    const chip = panel._activeToolChips['list_types']
    expect(chip.textContent).toContain('🔍 list_types')
    expect(chip.textContent).not.toContain('{}')
  })

  it('does nothing on tool_result for an unknown tool name', () => {
    const panel = makeMountedPanel()
    // No corresponding tool_use was received
    expect(() => {
      panel._onServerMessage({ type: 'tool_result', tool: 'ghost_tool', summary: '...' })
    }).not.toThrow()
  })
})

describe('ChatPanel._onServerMessage() — applying_edits', () => {
  it('shows edit notice with step count and rationale', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({
      type: 'applying_edits',
      step_count: 3,
      edit_rationale: 'Punchier opener',
    })

    const notices = Array.from(panel._messagesEl.querySelectorAll('div'))
    const notice = notices.find(el => el.textContent.includes('✏️'))
    expect(notice).toBeTruthy()
    expect(notice.textContent).toContain('3 edits')
    expect(notice.textContent).toContain('Punchier opener')
  })

  it('uses singular "edit" when step_count is 1', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({
      type: 'applying_edits',
      step_count: 1,
      edit_rationale: 'Minor tweak',
    })

    const notices = Array.from(panel._messagesEl.querySelectorAll('div'))
    const notice = notices.find(el => el.textContent.includes('✏️'))
    expect(notice.textContent).toContain('1 edit')
    expect(notice.textContent).not.toContain('1 edits')
  })

  it('sets state to "applying_edits"', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'applying_edits', step_count: 2, edit_rationale: '' })
    expect(panel._state).toBe('applying_edits')
  })
})

describe('ChatPanel._onServerMessage() — done', () => {
  it('returns to idle state', () => {
    const panel = makeMountedPanel()
    panel._setState('streaming')
    expect(panel._state).toBe('streaming')

    panel._onServerMessage({ type: 'done' })

    expect(panel._state).toBe('idle')
  })

  it('re-enables textarea and send button', () => {
    const panel = makeMountedPanel()
    panel._setState('streaming')
    expect(panel._inputEl.disabled).toBe(true)

    panel._onServerMessage({ type: 'done' })

    expect(panel._inputEl.disabled).toBe(false)
    expect(panel._sendBtn.disabled).toBe(false)
  })

  it('clears the current assistant bubble reference', () => {
    const panel = makeMountedPanel()
    panel._onServerMessage({ type: 'token', delta: 'Hello' })
    expect(panel._currentAssistantBubble).toBeTruthy()

    panel._onServerMessage({ type: 'done' })

    expect(panel._currentAssistantBubble).toBeNull()
  })
})

describe('ChatPanel unread badge via toolbar', () => {
  it('notifies toolbar._onChatMessage when token arrives while panel is closed', () => {
    const panel = makeMountedPanel()
    const mockToolbar = { _onChatMessage: vi.fn(), _unread: 0 }
    panel.setToolbar(mockToolbar)

    // Panel is closed (default)
    expect(panel.isOpen).toBe(false)
    panel._onServerMessage({ type: 'token', delta: 'Hi' })

    expect(mockToolbar._onChatMessage).toHaveBeenCalled()
  })

  it('does not notify toolbar when panel is open', () => {
    const panel = makeMountedPanel()
    const mockToolbar = { _onChatMessage: vi.fn(), _unread: 0 }
    panel.setToolbar(mockToolbar)
    panel.toggle()  // open it

    expect(panel.isOpen).toBe(true)
    panel._onServerMessage({ type: 'token', delta: 'Hi' })

    expect(mockToolbar._onChatMessage).not.toHaveBeenCalled()
  })
})

describe('EditToolbar.setChatPanel()', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('causes the 💬 Chat button to appear in editing state', () => {
    const toolbar = new EditToolbar({ cmsBase: 'http://cms.test', cmsElements: [] })
    toolbar.mount()
    toolbar.setState('editing')

    // No chat button before wiring
    let chatBtns = Array.from(toolbar.el.querySelectorAll('button')).filter(b =>
      b.textContent.includes('💬')
    )
    expect(chatBtns).toHaveLength(0)

    // Wire the panel
    const mockPanel = {
      toggle: vi.fn(),
      isOpen: false,
      setToolbar: vi.fn(),
    }
    toolbar.setChatPanel(mockPanel)

    chatBtns = Array.from(toolbar.el.querySelectorAll('button')).filter(b =>
      b.textContent.includes('💬')
    )
    expect(chatBtns).toHaveLength(1)
  })

  it('back-references the toolbar on the chat panel via setToolbar()', () => {
    const toolbar = new EditToolbar({ cmsBase: 'http://cms.test', cmsElements: [] })
    toolbar.mount()
    toolbar.setState('editing')

    const setToolbarSpy = vi.fn()
    const mockPanel = { toggle: vi.fn(), isOpen: false, setToolbar: setToolbarSpy }

    toolbar.setChatPanel(mockPanel)

    expect(setToolbarSpy).toHaveBeenCalledWith(toolbar)
  })

  it('_onChatMessage() increments _unread and updates badge label', () => {
    const toolbar = new EditToolbar({ cmsBase: 'http://cms.test', cmsElements: [] })
    toolbar.mount()
    toolbar.setState('editing')

    const mockPanel = {
      toggle: vi.fn(),
      isOpen: false,
      setToolbar: vi.fn(),
    }
    toolbar.setChatPanel(mockPanel)

    expect(toolbar._unread).toBe(0)
    toolbar._onChatMessage()
    expect(toolbar._unread).toBe(1)

    const chatBtn = Array.from(toolbar.el.querySelectorAll('button')).find(b =>
      b.textContent.includes('💬')
    )
    expect(chatBtn.textContent).toContain('(1)')
  })
})
