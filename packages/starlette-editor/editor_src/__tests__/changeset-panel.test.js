// @vitest-environment happy-dom
/**
 * Tests for components/changeset-panel.js — the merged changeset panel.
 *
 * This replaced two components, one per surface, neither a superset of the
 * other. These tests cover the union, and the two seams that let one component
 * serve both surfaces: injected navigation, and the mounting variant.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  fetchDirtyDocs: vi.fn(),
  fetchUnpublishedDocs: vi.fn(),
  fetchOpenChangesets: vi.fn(),
  fetchChangesetDiff: vi.fn(),
  publishChangeset: vi.fn(),
  createChangeset: vi.fn(),
  addDocToChangeset: vi.fn(),
  removeDocFromChangeset: vi.fn(),
  scheduleChangeset: vi.fn(),
  deleteChangeset: vi.fn(),
  setDraftDeleted: vi.fn(),
  discardDraft: vi.fn(),
  patchChangeset: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('../api.js', () => ({ ...mocks }))
vi.mock('../components/toast.js', () => ({ showToast: mocks.showToast }))

import { ChangesetPanel } from '../components/changeset-panel.js'
import { setActiveChangesetId } from '../changeset-store.js'

const DIRTY_DOCS = [
  { id: 'doc-1', doc_type: 'BlogPost', slug: 'hello-world', has_draft: true },
  { id: 'doc-2', doc_type: 'SiteSettings', slug: 'site-settings', has_draft: true },
]

const OPEN_CHANGESETS = [
  { id: 'cs-1', title: 'Q3 launch', status: 'open', document_count: 1, documents: [DIRTY_DOCS[0]] },
  { id: 'cs-2', title: 'Footer update', status: 'open', document_count: 0, documents: [] },
]

/** Mount a panel and load it with the fixtures. */
async function mountPanel(opts = {}) {
  const panel = new ChangesetPanel(opts)
  panel.mount()
  panel.visible = true
  await panel.refresh()
  return panel
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  document.body.innerHTML = ''
  mocks.fetchDirtyDocs.mockResolvedValue({ documents: DIRTY_DOCS })
  mocks.fetchUnpublishedDocs.mockResolvedValue({ documents: [] })
  mocks.fetchOpenChangesets.mockResolvedValue({ changesets: OPEN_CHANGESETS })
  mocks.fetchChangesetDiff.mockResolvedValue({ documents: [] })
  mocks.publishChangeset.mockResolvedValue({ id: 'cs-1', status: 'published' })
  mocks.createChangeset.mockResolvedValue({ id: 'cs-new', title: 'New' })
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('refresh', () => {
  it('loads dirty documents and open changesets', async () => {
    const panel = await mountPanel()

    expect(panel.dirtyDocs).toHaveLength(2)
    expect(panel.openChangesets).toHaveLength(2)
  })

  it('merges unpublished documents without duplicating them', async () => {
    mocks.fetchUnpublishedDocs.mockResolvedValue({ documents: [DIRTY_DOCS[0]] })

    const panel = await mountPanel()

    expect(panel.dirtyDocs.filter(d => d.id === 'doc-1')).toHaveLength(1)
  })

  it('empties rather than throwing when the API is unreachable', async () => {
    mocks.fetchOpenChangesets.mockRejectedValue(new Error('offline'))

    const panel = await mountPanel()

    expect(panel.dirtyDocs).toEqual([])
    expect(panel.openChangesets).toEqual([])
  })

  it('treats a document in no changeset as orphaned', async () => {
    const panel = await mountPanel()

    expect(panel._computeOrphans().map(d => d.id)).toEqual(['doc-2'])
  })
})

describe('publishing', () => {
  /** @returns {HTMLElement|null} */
  function confirmButton() {
    return [...document.querySelectorAll('button')].find(
      b => b.textContent === 'Confirm Publish',
    ) ?? null
  }

  it('opens a review step instead of publishing straight away', async () => {
    const panel = await mountPanel()

    await panel._handlePublish('cs-1')

    // Publishing triggers a production rebuild, so it takes a second step.
    expect(mocks.publishChangeset).not.toHaveBeenCalled()
    expect(confirmButton()).not.toBeNull()
  })

  it('fetches the diff to populate the review', async () => {
    const panel = await mountPanel()

    await panel._handlePublish('cs-1')

    expect(mocks.fetchChangesetDiff).toHaveBeenCalledWith('cs-1')
  })

  it('publishes once confirmed', async () => {
    const panel = await mountPanel()

    await panel._handlePublish('cs-1')
    confirmButton().click()

    await vi.waitFor(() => expect(mocks.publishChangeset).toHaveBeenCalledWith('cs-1'))
  })

  it('publishes nothing when the review is cancelled', async () => {
    const panel = await mountPanel()

    await panel._handlePublish('cs-1')
    const cancel = [...document.querySelectorAll('button')].find(b => b.textContent === 'Cancel')
    cancel.click()

    expect(mocks.publishChangeset).not.toHaveBeenCalled()
  })

  it('reports a diff that cannot be loaded without opening a review', async () => {
    mocks.fetchChangesetDiff.mockRejectedValue(new Error('boom'))
    const panel = await mountPanel()

    await panel._handlePublish('cs-1')

    expect(mocks.showToast).toHaveBeenCalledWith('error', 'Failed to load diff', 'boom')
    expect(confirmButton()).toBeNull()
  })
})

describe('active changeset', () => {
  it('reads the active id from the shared store', async () => {
    setActiveChangesetId('cs-2')

    const panel = await mountPanel()

    expect(panel.activeChangesetId).toBe('cs-2')
  })

  it('follows the store when another surface changes it', async () => {
    const panel = await mountPanel()

    setActiveChangesetId('cs-1')

    expect(panel.activeChangesetId).toBe('cs-1')
  })

  it('writes through the store when setting active', async () => {
    const panel = await mountPanel()

    await panel._setActive('cs-2')

    expect(panel.activeChangesetId).toBe('cs-2')
  })
})

describe('surface seams', () => {
  /** Action bars render only for the selected row, so select one. */
  function goToButtons(panel) {
    panel.expanded.add('cs-1')
    panel.selectedDocId = 'doc-1'
    panel._render()
    return [...panel.el.querySelectorAll('button')].filter(b => b.textContent === 'Go to')
  }

  it('offers Go to when navigation is injected', async () => {
    const panel = await mountPanel({ variant: 'shell', onNavigate: vi.fn() })

    expect(goToButtons(panel).length).toBeGreaterThan(0)
  })

  it('hides Go to where there is nowhere to go', async () => {
    const panel = await mountPanel({ variant: 'embed' })

    expect(goToButtons(panel)).toHaveLength(0)
  })

  it('routes Go to through the injected navigator', async () => {
    const onNavigate = vi.fn()
    const panel = await mountPanel({ variant: 'shell', onNavigate })

    await panel._handleGoToDoc('BlogPost', 'doc-1')

    expect(onNavigate).toHaveBeenCalledWith('BlogPost', 'doc-1')
  })

  it('does nothing on Go to when no navigator was given', async () => {
    const panel = await mountPanel({ variant: 'embed' })

    await expect(panel._handleGoToDoc('BlogPost', 'doc-1')).resolves.toBeUndefined()
  })

  it('gives the shell a resize handle', async () => {
    const panel = await mountPanel({ variant: 'shell' })

    expect(panel.el.children.length).toBeGreaterThan(1)
  })

  it('does not make the embed overlay a draggable window', async () => {
    const panel = await mountPanel({ variant: 'embed' })
    panel._render()

    // Geometry there would fight the host page layout and outlive the session.
    expect(localStorage.getItem('cms-changeset-panel-geometry')).toBeNull()
  })
})

describe('changeset actions', () => {
  it('creates a changeset and adds the document to it', async () => {
    const panel = await mountPanel()
    vi.spyOn(window, 'prompt').mockReturnValue('Release notes')

    await panel._promptAndCreate('doc-2')

    expect(mocks.createChangeset).toHaveBeenCalled()
    expect(mocks.addDocToChangeset).toHaveBeenCalledWith('cs-new', 'doc-2')
  })

  it('creates nothing when the title prompt is dismissed', async () => {
    const panel = await mountPanel()
    vi.spyOn(window, 'prompt').mockReturnValue(null)

    await panel._promptAndCreate('doc-2')

    expect(mocks.createChangeset).not.toHaveBeenCalled()
  })

  it('adds a document to an existing changeset', async () => {
    const panel = await mountPanel()

    await panel._handleAddToChangeset('doc-2', 'cs-1')

    expect(mocks.addDocToChangeset).toHaveBeenCalledWith('cs-1', 'doc-2')
  })

  it('removes a document from a changeset', async () => {
    const panel = await mountPanel()

    await panel._handleRemoveFromChangeset('cs-1', 'doc-1')

    expect(mocks.removeDocFromChangeset).toHaveBeenCalledWith('cs-1', 'doc-1')
  })

  it('moves a document between changesets', async () => {
    const panel = await mountPanel()

    await panel._handleMove('doc-1', 'cs-1', 'cs-2')

    expect(mocks.removeDocFromChangeset).toHaveBeenCalledWith('cs-1', 'doc-1')
    expect(mocks.addDocToChangeset).toHaveBeenCalledWith('cs-2', 'doc-1')
  })
})
