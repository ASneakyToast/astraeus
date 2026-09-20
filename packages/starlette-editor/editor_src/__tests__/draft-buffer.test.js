// @vitest-environment happy-dom

/**
 * Tests for draft-buffer.js — localStorage crash survival for unsaved edits.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { draftKey, saveDraft, writeDraft, loadDraft, clearDraft } from '../draft-buffer.js'

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('draftKey', () => {
  it('keys an existing document by id', () => {
    expect(draftKey('doc-1', 'post')).toBe('astraeus:draft:doc-1')
  })

  it('keys an unsaved new document by type', () => {
    expect(draftKey(null, 'post')).toBe('astraeus:draft:new:post')
  })

  it('does not collide a document id with a type', () => {
    expect(draftKey('post', 'post')).not.toBe(draftKey(null, 'post'))
  })
})

describe('writeDraft / loadDraft', () => {
  it('round-trips form data with a timestamp', () => {
    writeDraft('astraeus:draft:d1', { title: 'hello', count: 3 })

    const got = loadDraft('astraeus:draft:d1')
    expect(got.formData).toEqual({ title: 'hello', count: 3 })
    expect(Date.parse(got.savedAt)).not.toBeNaN()
  })

  it('returns null for a key with no buffer', () => {
    expect(loadDraft('astraeus:draft:missing')).toBeNull()
  })

  it('drops a corrupt entry rather than offering it back', () => {
    localStorage.setItem('astraeus:draft:d1', 'not json')

    expect(loadDraft('astraeus:draft:d1')).toBeNull()
    expect(localStorage.getItem('astraeus:draft:d1')).toBeNull()
  })

  it('rejects an entry with no usable form data', () => {
    localStorage.setItem('astraeus:draft:d1', JSON.stringify({ savedAt: 'x', formData: null }))

    expect(loadDraft('astraeus:draft:d1')).toBeNull()
  })
})

describe('saveDraft', () => {
  it('debounces so typing does not thrash storage', () => {
    saveDraft('astraeus:draft:d1', { title: 'a' })
    saveDraft('astraeus:draft:d1', { title: 'ab' })
    saveDraft('astraeus:draft:d1', { title: 'abc' })

    expect(loadDraft('astraeus:draft:d1')).toBeNull()

    vi.runAllTimers()

    expect(loadDraft('astraeus:draft:d1').formData).toEqual({ title: 'abc' })
  })
})

describe('clearDraft', () => {
  it('removes the buffer', () => {
    writeDraft('astraeus:draft:d1', { title: 'hello' })
    clearDraft('astraeus:draft:d1')

    expect(loadDraft('astraeus:draft:d1')).toBeNull()
  })

  it('cancels a pending write that would recreate it', () => {
    saveDraft('astraeus:draft:d1', { title: 'hello' })
    clearDraft('astraeus:draft:d1')

    vi.runAllTimers()

    expect(loadDraft('astraeus:draft:d1')).toBeNull()
  })
})

describe('quota handling', () => {
  it('evicts the oldest buffer and retries', () => {
    localStorage.setItem(
      'astraeus:draft:old',
      JSON.stringify({ savedAt: '2020-01-01T00:00:00.000Z', formData: { a: 1 } }),
    )
    localStorage.setItem(
      'astraeus:draft:recent',
      JSON.stringify({ savedAt: '2030-01-01T00:00:00.000Z', formData: { b: 2 } }),
    )

    // Spy the instance, not Storage.prototype — a prototype spy does not
    // intercept the module's calls under happy-dom. Later calls fall through
    // to the real implementation, which is what the retry needs.
    const spy = vi.spyOn(localStorage, 'setItem')
    spy.mockImplementationOnce(() => { throw new DOMException('full', 'QuotaExceededError') })

    writeDraft('astraeus:draft:new', { c: 3 })

    expect(loadDraft('astraeus:draft:old')).toBeNull()
    expect(loadDraft('astraeus:draft:recent')).not.toBeNull()
    expect(loadDraft('astraeus:draft:new').formData).toEqual({ c: 3 })

    spy.mockRestore()
  })

  it('gives up quietly when there is nothing left to evict', () => {
    const spy = vi.spyOn(localStorage, 'setItem')
    spy.mockImplementation(() => { throw new DOMException('full', 'QuotaExceededError') })

    expect(() => writeDraft('astraeus:draft:d1', { a: 1 })).not.toThrow()

    spy.mockRestore()
  })
})
