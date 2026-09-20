/**
 * Tests for the unsaved-edit guards on selectType and selectDoc.
 *
 * Both actions replace state.formData wholesale, so a dirty document has to
 * prompt before they run — otherwise the edits are gone with no way back.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  showConfirm: vi.fn(),
  fetchDocuments: vi.fn(),
  fetchDocument: vi.fn(),
  destroyPmInstances: vi.fn(),
}))

vi.mock('../components/confirm.js', () => ({ showConfirm: mocks.showConfirm }))
vi.mock('../components/toast.js', () => ({ showToast: vi.fn() }))
vi.mock('../prosemirror/mount.js', () => ({ destroyPmInstances: mocks.destroyPmInstances }))
vi.mock('../prosemirror/markdown.js', () => ({ pmDocToMarkdown: vi.fn() }))
vi.mock('../changeset-store.js', () => ({
  setActiveChangesetId: vi.fn(),
  getActiveChangesetId: vi.fn(() => null),
}))
vi.mock('../api.js', () => ({
  fetchDocuments: mocks.fetchDocuments,
  fetchDocument: mocks.fetchDocument,
  createDocument: vi.fn(),
  patchDocument: vi.fn(),
  setDraftPublishState: vi.fn(),
  setDraftDeleted: vi.fn(),
  addDocToChangeset: vi.fn(),
}))

import { selectType, selectDoc } from '../standard/actions.js'
import { state } from '../state.js'

beforeEach(() => {
  vi.clearAllMocks()
  mocks.fetchDocuments.mockResolvedValue({ documents: [], total: 0 })
  mocks.fetchDocument.mockResolvedValue({ id: 'doc-2', body: { title: 'saved' }, slug: 'saved' })

  state.activeType = 'post'
  state.activeDocId = 'doc-1'
  state.formData = { title: 'unsaved work' }
  state.isDirty = false
})

describe('selectType', () => {
  it('does not prompt when the document is clean', async () => {
    await selectType('page')

    expect(mocks.showConfirm).not.toHaveBeenCalled()
    expect(state.activeType).toBe('page')
  })

  it('keeps the edits when the user cancels', async () => {
    state.isDirty = true
    mocks.showConfirm.mockResolvedValue(false)

    await selectType('page')

    expect(mocks.showConfirm).toHaveBeenCalledOnce()
    expect(state.activeType).toBe('post')
    expect(state.formData).toEqual({ title: 'unsaved work' })
    expect(state.isDirty).toBe(true)
    expect(mocks.destroyPmInstances).not.toHaveBeenCalled()
  })

  it('discards the edits when the user confirms', async () => {
    state.isDirty = true
    mocks.showConfirm.mockResolvedValue(true)

    await selectType('page')

    expect(state.activeType).toBe('page')
    expect(state.formData).toEqual({})
    expect(state.isDirty).toBe(false)
  })
})

describe('selectDoc', () => {
  it('does not prompt when the document is clean', async () => {
    await selectDoc('doc-2')

    expect(mocks.showConfirm).not.toHaveBeenCalled()
    expect(state.activeDocId).toBe('doc-2')
  })

  it('keeps the edits when the user cancels', async () => {
    state.isDirty = true
    mocks.showConfirm.mockResolvedValue(false)

    await selectDoc('doc-2')

    expect(mocks.showConfirm).toHaveBeenCalledOnce()
    expect(state.activeDocId).toBe('doc-1')
    expect(state.formData).toEqual({ title: 'unsaved work' })
    expect(state.isDirty).toBe(true)
    expect(mocks.fetchDocument).not.toHaveBeenCalled()
  })

  it('discards the edits when the user confirms', async () => {
    state.isDirty = true
    mocks.showConfirm.mockResolvedValue(true)

    await selectDoc('doc-2')

    expect(state.activeDocId).toBe('doc-2')
    expect(state.formData).toEqual({ title: 'saved', __slug: 'saved' })
    expect(state.isDirty).toBe(false)
  })

  it('does not prompt when reselecting the active document', async () => {
    state.isDirty = true

    await selectDoc('doc-1')

    expect(mocks.showConfirm).not.toHaveBeenCalled()
    expect(state.formData).toEqual({ title: 'unsaved work' })
  })
})
