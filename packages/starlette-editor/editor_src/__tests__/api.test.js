/**
 * api.js — request shapes the editor depends on.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchDocument } from '../api.js'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchDocument', () => {
  it('asks for the draft body', async () => {
    // Without ?draft=true the API returns the published body, so reopening a
    // document with unpublished edits showed the old content — and typing into
    // its rich-text editor overwrote the real draft over the collab socket.
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 'doc-1' }) })
    vi.stubGlobal('fetch', fetchMock)

    await fetchDocument('doc-1')

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/documents/doc-1?draft=true')
  })
})
