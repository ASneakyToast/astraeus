// @vitest-environment happy-dom
/**
 * Tests for embed/changeset-panel.js — ChangesetPanel logic.
 *
 * DOM manipulation is minimal in these tests; we focus on the async
 * logic layer (fetch calls, state population, confirmation guards).
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { ChangesetPanel } from '../embed/changeset-panel.js'

// ── Fixtures ──────────────────────────────────────────────────────────────────

const DIRTY_DOCS = [
  { id: 'doc-1', doc_type: 'BlogPost', slug: 'hello-world', has_draft: true },
  { id: 'doc-2', doc_type: 'SiteSettings', slug: 'site-settings', has_draft: true },
]

const OPEN_CHANGESETS = [
  { id: 'cs-1', title: 'Q3 launch', status: 'open', document_count: 2 },
  { id: 'cs-2', title: 'Footer update', status: 'open', document_count: 1 },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeFetch(docsPayload = DIRTY_DOCS, csPayload = OPEN_CHANGESETS) {
  return vi.fn(url => {
    const u = String(url)
    if (u.includes('has_draft=true')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ documents: docsPayload }) })
    }
    if (u.includes('status=open')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ changesets: csPayload }) })
    }
    if (u.includes('/publish')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 'cs-1', status: 'published' }) })
    }
    if (u.includes('/schedule')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 'cs-1', status: 'scheduled' }) })
    }
    // Generic POST (add doc, create changeset, delete)
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ id: 'cs-new', title: 'new cs' }) })
  })
}

function makePanel(fetchMock) {
  const panel = new ChangesetPanel({ cmsBase: 'http://cms.test', toolbar: {} })
  // Attach a minimal DOM element so _render() doesn't throw
  const el = document.createElement('div')
  document.body.appendChild(el)
  panel.el = el
  // Override fetch
  vi.stubGlobal('fetch', fetchMock)
  return panel
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('ChangesetPanel.refresh()', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('calls both /api/documents?has_draft=true and /api/changesets?status=open', async () => {
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)

    await panel.refresh()

    const calls = fetchMock.mock.calls.map(c => c[0])
    expect(calls.some(u => u.includes('has_draft=true'))).toBe(true)
    expect(calls.some(u => u.includes('status=open'))).toBe(true)
  })

  it('populates dirtyDocs and openChangesets from responses', async () => {
    const panel = makePanel(makeFetch())

    await panel.refresh()

    expect(panel.dirtyDocs).toHaveLength(2)
    expect(panel.dirtyDocs[0].id).toBe('doc-1')
    expect(panel.openChangesets).toHaveLength(2)
    expect(panel.openChangesets[0].id).toBe('cs-1')
  })

  it('handles missing keys gracefully (uses empty arrays)', async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    )
    const panel = makePanel(fetchMock)

    await panel.refresh()

    expect(panel.dirtyDocs).toEqual([])
    expect(panel.openChangesets).toEqual([])
  })
})

describe('ChangesetPanel._addToChangeset()', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('POSTs to /api/changesets/{csId}/documents/{docId} then refreshes', async () => {
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)

    await panel._addToChangeset('doc-1', 'cs-1')

    const postCalls = fetchMock.mock.calls.filter(c => c[1]?.method === 'POST')
    expect(postCalls.length).toBeGreaterThanOrEqual(1)
    const addUrl = postCalls[0][0]
    expect(addUrl).toContain('/api/changesets/cs-1/documents/doc-1')

    // refresh() follows — verify at least the GET calls were made
    const getCalls = fetchMock.mock.calls.filter(c => !c[1]?.method || c[1].method === 'GET')
    expect(getCalls.length).toBeGreaterThan(0)
  })
})

describe('ChangesetPanel._createAndAdd()', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('first creates a changeset then adds the doc', async () => {
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)

    await panel._createAndAdd('doc-1', 'My release')

    const postCalls = fetchMock.mock.calls
      .filter(c => c[1]?.method === 'POST')
      .map(c => c[0])

    // First POST creates changeset
    expect(postCalls[0]).toContain('/api/changesets')
    expect(postCalls[0]).not.toContain('/documents/')

    // Second POST adds the document
    expect(postCalls[1]).toContain('/documents/doc-1')
  })

  it('sends the title in the creation body', async () => {
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)

    await panel._createAndAdd('doc-1', 'Sprint 42')

    const createCall = fetchMock.mock.calls.find(
      c => c[1]?.method === 'POST' && !String(c[0]).includes('/documents/')
    )
    const body = JSON.parse(createCall[1].body)
    expect(body.title).toBe('Sprint 42')
  })

  it('skips the add-document step when docId is null', async () => {
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)

    await panel._createAndAdd(null, 'Empty cs')

    const postCalls = fetchMock.mock.calls.filter(c => c[1]?.method === 'POST')
    // Only the create call, no /documents/ call
    expect(postCalls.every(c => !String(c[0]).includes('/documents/'))).toBe(true)
  })
})

describe('ChangesetPanel._publishChangeset()', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('POSTs to /api/changesets/{id}/publish', async () => {
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)

    await panel._publishChangeset('cs-1')

    const publishCall = fetchMock.mock.calls.find(c =>
      c[1]?.method === 'POST' && String(c[0]).includes('/publish')
    )
    expect(publishCall).toBeDefined()
    expect(publishCall[0]).toContain('/api/changesets/cs-1/publish')
  })

  it('calls _showToast then refreshes', async () => {
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)
    const toastSpy = vi.spyOn(panel, '_showToast')
    const refreshSpy = vi.spyOn(panel, 'refresh')

    await panel._publishChangeset('cs-1')

    expect(toastSpy).toHaveBeenCalledWith('Published — site rebuilding')
    expect(refreshSpy).toHaveBeenCalled()
  })
})

describe('ChangesetPanel._deleteChangeset()', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('sends DELETE to /api/changesets/{id} after confirm', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true))
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)

    await panel._deleteChangeset('cs-1')

    const deleteCall = fetchMock.mock.calls.find(c => c[1]?.method === 'DELETE')
    expect(deleteCall).toBeDefined()
    expect(deleteCall[0]).toContain('/api/changesets/cs-1')
  })

  it('does not call fetch when confirm returns false', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false))
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)

    await panel._deleteChangeset('cs-1')

    const deleteCalls = fetchMock.mock.calls.filter(c => c[1]?.method === 'DELETE')
    expect(deleteCalls).toHaveLength(0)
  })
})

describe('ChangesetPanel.toggle()', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('calls refresh() when toggling to visible', async () => {
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)
    const refreshSpy = vi.spyOn(panel, 'refresh')

    expect(panel.visible).toBe(false)
    await panel.toggle()

    expect(panel.visible).toBe(true)
    expect(refreshSpy).toHaveBeenCalled()
  })

  it('does not call refresh() when toggling to hidden', async () => {
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)
    panel.visible = true
    const refreshSpy = vi.spyOn(panel, 'refresh')

    await panel.toggle()

    expect(panel.visible).toBe(false)
    expect(refreshSpy).not.toHaveBeenCalled()
  })
})

describe('ChangesetPanel._scheduleChangeset()', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('POSTs { publish_at } ISO string to /schedule endpoint', async () => {
    const fetchMock = makeFetch()
    const panel = makePanel(fetchMock)

    // Simulate a row element with a picker that has a value set
    const rowEl = document.createElement('div')
    document.body.appendChild(rowEl)

    // Call _scheduleChangeset — it inserts a picker into rowEl
    panel._scheduleChangeset('cs-1', rowEl)

    // Find the input and set a value, then click confirm
    const input = rowEl.querySelector('input[type="datetime-local"]')
    const confirmBtn = rowEl.querySelector('button')
    expect(input).toBeDefined()
    expect(confirmBtn).toBeDefined()

    // Set a datetime value
    input.value = '2026-09-01T10:00'
    confirmBtn.click()

    // Allow promise to settle
    await new Promise(r => setTimeout(r, 0))

    const scheduleCall = fetchMock.mock.calls.find(c =>
      c[1]?.method === 'POST' && String(c[0]).includes('/schedule')
    )
    expect(scheduleCall).toBeDefined()
    expect(scheduleCall[0]).toContain('/api/changesets/cs-1/schedule')

    const body = JSON.parse(scheduleCall[1].body)
    expect(body.publish_at).toBe(new Date('2026-09-01T10:00').toISOString())
  })
})
