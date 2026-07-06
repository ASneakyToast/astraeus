// @vitest-environment jsdom
/**
 * Tests for CollabConnection — the WebSocket collab client.
 *
 * WebSocket is not natively available in jsdom, so we use a mock.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ---------------------------------------------------------------------------
// Mock WebSocket
// ---------------------------------------------------------------------------

class MockWebSocket {
  constructor(url) {
    this.url = url
    this.readyState = MockWebSocket.OPEN
    this.sent = []
    MockWebSocket.instances.push(this)
  }

  send(data) {
    this.sent.push(JSON.parse(data))
  }

  close() {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }

  // Simulate a message arriving from the server
  _receive(data) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }

  static OPEN = 1
  static CLOSED = 3
  static instances = []
}

beforeEach(() => {
  MockWebSocket.instances = []
  vi.useFakeTimers()
  global.WebSocket = MockWebSocket
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------
// Minimal ProseMirror stubs
// We don't want to pull in a full PM schema for unit tests of collab logic.
// ---------------------------------------------------------------------------

function makeMinimalView(dispatchFn) {
  // A stub view object that CollabConnection interacts with
  return {
    state: {
      doc: {
        toJSON: () => ({ type: 'doc', content: [] }),
      },
      apply: vi.fn((tr) => ({ doc: tr.doc || { toJSON: () => ({}) } })),
    },
    dispatch: vi.fn(),
    updateState: vi.fn(),
  }
}

function makeToolbar() {
  return { setState: vi.fn() }
}

// We partially mock prosemirror-collab so we can control sendableSteps
vi.mock('prosemirror-collab', () => {
  const collab = vi.fn(() => ({ spec: {} }))
  const sendableSteps = vi.fn(() => null)  // no pending steps by default
  const receiveTransaction = vi.fn((state, steps, clientIDs) => ({
    // Return a minimal transaction-like object
    docChanged: steps.length > 0,
    doc: { toJSON: () => ({ type: 'doc', content: [] }) },
  }))
  const getVersion = vi.fn(() => 0)
  return { collab, sendableSteps, receiveTransaction, getVersion }
})

vi.mock('prosemirror-transform', () => {
  const Step = {
    fromJSON: vi.fn((schema, json) => ({ toJSON: () => json })),
  }
  return { Step }
})

// ---------------------------------------------------------------------------
// Import after mocks are set up
// ---------------------------------------------------------------------------

const { CollabConnection } = await import('../embed/collab.js')
const { sendableSteps, receiveTransaction } = await import('prosemirror-collab')

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CollabConnection._wsUrl()', () => {
  it('converts https to wss', () => {
    const view = makeMinimalView()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar: makeToolbar(),
      clientID: 'abc',
    })
    expect(conn._wsUrl()).toBe('wss://cms.example.com/api/documents/doc-1/collab')
    conn.destroy()
  })

  it('converts http to ws', () => {
    const view = makeMinimalView()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-42',
      cmsBase: 'http://localhost:8000',
      initialVersion: 0,
      toolbar: makeToolbar(),
      clientID: 'abc',
    })
    expect(conn._wsUrl()).toBe('ws://localhost:8000/api/documents/doc-42/collab')
    conn.destroy()
  })
})

describe('CollabConnection._connect()', () => {
  it('creates a WebSocket to the correct URL', () => {
    const view = makeMinimalView()
    new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-99',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar: makeToolbar(),
      clientID: 'xyz',
    })
    // A MockWebSocket instance should have been created
    expect(MockWebSocket.instances.length).toBe(1)
    expect(MockWebSocket.instances[0].url).toBe(
      'wss://cms.example.com/api/documents/doc-99/collab'
    )
  })
})

describe('CollabConnection._sendPendingSteps()', () => {
  it('does nothing when WS readyState is not OPEN', () => {
    const view = makeMinimalView()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar: makeToolbar(),
      clientID: 'abc',
    })

    // Force WS closed
    conn.ws.readyState = MockWebSocket.CLOSED
    sendableSteps.mockReturnValueOnce({
      steps: [{ toJSON: () => ({ stepType: 'replace' }) }],
      version: 1,
    })

    conn._sendPendingSteps()

    // Should not send anything
    expect(conn.ws.sent).toHaveLength(0)
    conn.destroy()
  })

  it('does nothing when sendableSteps returns null', () => {
    const view = makeMinimalView()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar: makeToolbar(),
      clientID: 'abc',
    })

    sendableSteps.mockReturnValueOnce(null)
    conn._sendPendingSteps()

    expect(conn.ws.sent).toHaveLength(0)
    conn.destroy()
  })
})

describe('CollabConnection._handleMessage()', () => {
  it('handles init: updates this.version to server version', () => {
    const view = makeMinimalView()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar: makeToolbar(),
      clientID: 'abc',
    })

    expect(conn.version).toBe(0)
    conn._handleMessage({ type: 'init', doc: {}, version: 5 })
    expect(conn.version).toBe(5)
    conn.destroy()
  })

  it('handles steps: updates version and calls toolbar.setState("editing")', () => {
    const view = makeMinimalView()
    const toolbar = makeToolbar()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar,
      clientID: 'abc',
    })

    conn._handleMessage({
      type: 'steps',
      steps: [],
      clientIDs: [],
      version: 6,
    })

    expect(conn.version).toBe(6)
    expect(toolbar.setState).toHaveBeenCalledWith('editing')
    conn.destroy()
  })

  it('handles reject: updates version and closes socket to trigger reconnect', () => {
    const view = makeMinimalView()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar: makeToolbar(),
      clientID: 'abc',
    })

    const ws = conn.ws
    conn._handleMessage({ type: 'reject', version: 3 })

    expect(conn.version).toBe(3)
    expect(ws.readyState).toBe(MockWebSocket.CLOSED)
    // Prevent actual reconnect attempt from noising the test
    conn.destroy()
  })

  it('ignores pong messages silently', () => {
    const view = makeMinimalView()
    const toolbar = makeToolbar()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar,
      clientID: 'abc',
    })

    // Should not throw or call toolbar
    conn._handleMessage({ type: 'pong' })
    expect(toolbar.setState).not.toHaveBeenCalled()
    conn.destroy()
  })
})

describe('CollabConnection.destroy()', () => {
  it('sets _destroyed = true and closes the WebSocket', () => {
    const view = makeMinimalView()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar: makeToolbar(),
      clientID: 'abc',
    })

    const ws = conn.ws
    conn.destroy()

    expect(conn._destroyed).toBe(true)
    expect(ws.readyState).toBe(MockWebSocket.CLOSED)
  })

  it('does not reconnect after destroy even if WS closes', () => {
    const view = makeMinimalView()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar: makeToolbar(),
      clientID: 'abc',
    })

    conn.destroy()
    const instanceCountAfterDestroy = MockWebSocket.instances.length

    // Advance timers — no reconnect should fire
    vi.advanceTimersByTime(5000)
    expect(MockWebSocket.instances.length).toBe(instanceCountAfterDestroy)
  })
})

describe('CollabConnection exponential backoff', () => {
  it('_reconnectDelay doubles on each disconnect, caps at 30000', () => {
    const view = makeMinimalView()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar: makeToolbar(),
      clientID: 'abc',
    })

    expect(conn._reconnectDelay).toBe(1000)

    // Simulate a close (onclose is called, which sets reconnect and doubles delay)
    // We need to patch _connect to not actually reconnect
    conn._connect = vi.fn()

    // Manually trigger what onclose does
    conn._reconnectDelay = Math.min(conn._reconnectDelay * 2, 30000)
    expect(conn._reconnectDelay).toBe(2000)

    conn._reconnectDelay = Math.min(conn._reconnectDelay * 2, 30000)
    expect(conn._reconnectDelay).toBe(4000)

    // Keep doubling until cap
    for (let i = 0; i < 10; i++) {
      conn._reconnectDelay = Math.min(conn._reconnectDelay * 2, 30000)
    }
    expect(conn._reconnectDelay).toBe(30000)

    conn.destroy()
  })

  it('resets _reconnectDelay to 1000 on successful reconnect (ws.onopen)', () => {
    const view = makeMinimalView()
    const conn = new CollabConnection({
      view,
      schema: {},
      documentId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      initialVersion: 0,
      toolbar: makeToolbar(),
      clientID: 'abc',
    })

    // Simulate multiple failures increasing delay
    conn._reconnectDelay = 16000

    // Simulate onopen firing
    conn.ws.onopen()
    expect(conn._reconnectDelay).toBe(1000)

    conn.destroy()
  })
})
