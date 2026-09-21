// @vitest-environment happy-dom
/**
 * Tests for components/pending-view.js — the small-screen triage landing.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  fetchDirtyDocs: vi.fn(),
  fetchUnpublishedDocs: vi.fn(),
  discardDraft: vi.fn(),
  showConfirm: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('../api.js', () => ({
  fetchDirtyDocs: mocks.fetchDirtyDocs,
  fetchUnpublishedDocs: mocks.fetchUnpublishedDocs,
  discardDraft: mocks.discardDraft,
}))
vi.mock('../components/confirm.js', () => ({ showConfirm: mocks.showConfirm }))
vi.mock('../components/toast.js', () => ({ showToast: mocks.showToast }))

import { PendingView } from '../components/pending-view.js'

const EDITED = { id: 'd1', doc_type: 'BlogPost', slug: 'hello', published: true, has_draft: true }
const NEVER = { id: 'd2', doc_type: 'BlogPost', slug: 'draft-post', published: false }

beforeEach(() => {
  vi.clearAllMocks()
  mocks.fetchDirtyDocs.mockResolvedValue({ documents: [EDITED] })
  mocks.fetchUnpublishedDocs.mockResolvedValue({ documents: [NEVER] })
})

/** @returns {PendingView} mounted and loaded */
async function mount(opts = {}) {
  const view = new PendingView({ onOpen: vi.fn(), ...opts })
  view.mount()
  await view.refresh()
  return view
}

describe('loading', () => {
  it('lists everything unpublished', async () => {
    const view = await mount()

    expect(view.docs.map(d => d.id)).toEqual(['d1', 'd2'])
  })

  it('does not list a document twice when both queries return it', async () => {
    mocks.fetchUnpublishedDocs.mockResolvedValue({ documents: [EDITED] })

    const view = await mount()

    expect(view.docs).toHaveLength(1)
  })

  it('reports a failure rather than rendering a misleading empty state', async () => {
    mocks.fetchDirtyDocs.mockRejectedValue(new Error('offline'))

    const view = await mount()

    expect(mocks.showToast).toHaveBeenCalledWith(
      'error', 'Could not load pending changes', 'offline',
    )
    expect(view.docs).toEqual([])
  })
})

describe('rendering', () => {
  it('says why each document is outstanding', async () => {
    const view = await mount()
    const meta = [...view.el.querySelectorAll('.pending-view__meta')].map(n => n.textContent)

    expect(meta[0]).toContain('Edited since publishing')
    expect(meta[1]).toContain('Never published')
  })

  it('calls out a staged deletion', async () => {
    mocks.fetchDirtyDocs.mockResolvedValue({
      documents: [{ ...EDITED, draft_deleted: true }],
    })
    mocks.fetchUnpublishedDocs.mockResolvedValue({ documents: [] })

    const view = await mount()

    expect(view.el.querySelector('.pending-view__meta').textContent)
      .toContain('Staged for deletion')
  })

  it('invites an action when nothing is pending', async () => {
    mocks.fetchDirtyDocs.mockResolvedValue({ documents: [] })
    mocks.fetchUnpublishedDocs.mockResolvedValue({ documents: [] })

    const view = await mount()

    expect(view.el.textContent).toContain('Everything is published')
    expect(view.el.textContent).toContain('Pick a type to start something new')
  })

  it('counts what is outstanding', async () => {
    const view = await mount()

    expect(view.el.querySelector('.pending-view__count').textContent).toBe('2 unpublished')
  })

  it('offers publish only when there is somewhere to route it', async () => {
    const withPublish = await mount({ onPublish: vi.fn() })
    expect(withPublish.el.textContent).toContain('Review & publish')

    const without = await mount()
    expect(without.el.textContent).not.toContain('Review & publish')
  })
})

describe('actions', () => {
  it('opens a document', async () => {
    const onOpen = vi.fn()
    const view = await mount({ onOpen })

    view.el.querySelector('.pending-view__open').click()

    expect(onOpen).toHaveBeenCalledWith('BlogPost', 'd1')
  })

  it('routes publish through the review step rather than publishing here', async () => {
    const onPublish = vi.fn()
    const view = await mount({ onPublish })

    ;[...view.el.querySelectorAll('button')]
      .find(b => b.textContent === 'Review & publish')
      .click()

    expect(onPublish).toHaveBeenCalled()
  })

  it('confirms before discarding a draft', async () => {
    mocks.showConfirm.mockResolvedValue(false)
    const view = await mount()

    await view._discard(EDITED)

    expect(mocks.showConfirm).toHaveBeenCalled()
    expect(mocks.discardDraft).not.toHaveBeenCalled()
  })

  it('discards once confirmed', async () => {
    mocks.showConfirm.mockResolvedValue(true)
    mocks.discardDraft.mockResolvedValue({})
    const view = await mount()

    await view._discard(EDITED)

    expect(mocks.discardDraft).toHaveBeenCalledWith('d1')
  })

  it('reports a discard that fails', async () => {
    mocks.showConfirm.mockResolvedValue(true)
    mocks.discardDraft.mockRejectedValue(new Error('nope'))
    const view = await mount()

    await view._discard(EDITED)

    expect(mocks.showToast).toHaveBeenCalledWith('error', 'Could not discard draft', 'nope')
  })
})
