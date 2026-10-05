// @vitest-environment jsdom
/**
 * Drafts on a listing page: the page contract, loading by lens, and card rendering.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  DEFAULT_LENS,
  LENS_ALL,
  LENS_PROD,
  changesetLens,
  changesetOfLens,
  findDraftSlots,
  getLens,
  renderDraftCard,
  setLens,
  syncDraftCards,
} from '../embed/drafts.js'

const CMS = 'https://cms.example.com'

const pm = (text) => ({ type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] })

const doc = (id, body = {}, extra = {}) => ({
  id,
  doc_type: 'blog_post',
  slug: id,
  published: false,
  has_draft: false,
  draft_deleted: null,
  body: { title: `Title ${id}`, description: `About ${id}`, publish_date: '2026-09-01', body_markdown: pm(`Body of ${id}`), ...body },
  ...extra,
})

/** The page: a feed with one live card, plus the site's card template. */
function mountPage() {
  document.body.innerHTML = `
    <div data-cms-list="blog_post" id="feed">
      <article data-cms-id="live-1" data-cms-type="blog_post"><span data-cms-field="title">Live</span></article>
      <article data-cms-id="live-2" data-cms-type="blog_post"><span data-cms-field="title">Live two</span></article>
    </div>
    <template data-cms-draft-template="blog_post">
      <article class="log-record">
        <time data-cms-fill="publish_date" data-cms-fill-format="date"></time>
        <h2><span data-cms-field="title" data-cms-fill="title"></span></h2>
        <p data-cms-field="description" data-cms-fill="description"></p>
        <div data-cms-field="body_markdown" data-cms-collapsible data-cms-fill="body_markdown" data-cms-fill-format="excerpt"></div>
      </article>
    </template>
  `
}

/**
 * A fake CMS. `unpublished` is the list endpoint's answer; `byId` what the
 * single-document endpoint returns (the draft applied); `edited` the live posts
 * with unpublished edits; `changesets` maps id → documents it holds.
 */
function fakeCms({ unpublished = [], byId = {}, edited = [], changesets = {}, failList = false } = {}) {
  const calls = []
  const fetchMock = vi.fn(async (url) => {
    calls.push(url)
    const u = new URL(url)
    const json = (data) => ({ ok: true, json: async () => data })
    if (u.pathname === '/api/documents') {
      if (failList) return { ok: false, status: 500, json: async () => ({}) }
      if (u.searchParams.get('published') === 'false') {
        const type = u.searchParams.get('type')
        return json({ documents: unpublished.filter((d) => !type || d.doc_type === type) })
      }
      if (u.searchParams.get('has_draft') === 'true') return json({ documents: edited.map((id) => ({ id })) })
    }
    const single = u.pathname.match(/^\/api\/documents\/([^/]+)$/)
    if (single) {
      const found = byId[single[1]] ?? unpublished.find((d) => d.id === single[1])
      return found ? json(found) : { ok: false, status: 404, json: async () => ({}) }
    }
    const cs = u.pathname.match(/^\/api\/changesets\/([^/]+)$/)
    if (cs) return json({ id: cs[1], documents: changesets[cs[1]] ?? [] })
    return { ok: false, status: 404, json: async () => ({}) }
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

beforeEach(() => {
  localStorage.clear()
  mountPage()
})

afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('lens', () => {
  it('defaults to showing every draft, and remembers a choice', () => {
    expect(DEFAULT_LENS).toBe(LENS_ALL)
    expect(getLens()).toBe(LENS_ALL)
    setLens(LENS_PROD)
    expect(getLens()).toBe(LENS_PROD)
  })

  it('names a changeset and reads it back', () => {
    expect(changesetOfLens(changesetLens('abc'))).toBe('abc')
    expect(changesetOfLens(LENS_ALL)).toBeNull()
    expect(changesetOfLens(LENS_PROD)).toBeNull()
  })
})

describe('findDraftSlots', () => {
  it('finds a list that has a card template', () => {
    const slots = findDraftSlots()
    expect(slots).toHaveLength(1)
    expect(slots[0].docType).toBe('blog_post')
    expect(slots[0].list.id).toBe('feed')
  })

  it('ignores a list with no template, so a site that has not opted in is untouched', () => {
    document.querySelector('template').remove()
    expect(findDraftSlots()).toEqual([])
  })
})

describe('renderDraftCard', () => {
  const template = () => document.querySelector('template')

  it('fills the template from the draft and tags it for the editor', () => {
    const card = renderDraftCard(template(), doc('d1', { publish_date: '2026-07-04T00:00:00Z' }))

    expect(card.dataset.cmsId).toBe('d1')
    expect(card.dataset.cmsType).toBe('blog_post')
    expect(card.hasAttribute('data-cms-draft-card')).toBe(true)
    expect(card.querySelector('[data-cms-fill="title"]').textContent).toBe('Title d1')
    expect(card.querySelector('[data-cms-fill="description"]').textContent).toBe('About d1')
    expect(card.querySelector('[data-cms-fill="body_markdown"]').textContent).toBe('Body of d1')
  })

  it('shows the date in UTC, as the site does', () => {
    const card = renderDraftCard(template(), doc('d1', { publish_date: '2026-07-01' }))
    const time = card.querySelector('time')
    expect(time.textContent).toBe('July 1, 2026')
    expect(time.getAttribute('datetime')).toBe('2026-07-01T00:00:00.000Z')
  })

  it('copes with a missing date and title', () => {
    const card = renderDraftCard(template(), doc('d1', { publish_date: undefined, title: '' }))
    expect(card.querySelector('time').textContent).toBe('No date')
    expect(card.querySelector('[data-cms-fill="title"]').textContent).toBe('Untitled draft')
  })

  it('cuts a long body to a preview', () => {
    const card = renderDraftCard(template(), doc('d1', { body_markdown: pm('word '.repeat(200)) }))
    const text = card.querySelector('[data-cms-fill="body_markdown"]').textContent
    expect(text.length).toBeLessThanOrEqual(301)
    expect(text.endsWith('…')).toBe(true)
  })

  it('labels the card as a draft that is not live', () => {
    const card = renderDraftCard(template(), doc('d1'))
    expect(card.querySelector('[data-cms-draft-pill="draft"]').textContent).toContain('not live')
  })

  it('does not touch the template, so the next card starts clean', () => {
    renderDraftCard(template(), doc('d1'))
    expect(template().content.querySelector('[data-cms-id]')).toBeNull()
    expect(template().content.querySelector('[data-cms-fill="title"]').textContent).toBe('')
  })
})

describe('syncDraftCards', () => {
  const feedIds = () => [...document.querySelectorAll('#feed > [data-cms-id]')].map((el) => el.dataset.cmsId)

  it('adds a card for every unpublished post when the lens is "all"', async () => {
    fakeCms({ unpublished: [doc('d1'), doc('d2')] })
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })

    expect(added.map((el) => el.dataset.cmsId).sort()).toEqual(['d1', 'd2'])
    // Drafts sit above the live posts.
    expect(feedIds().slice(2).sort()).toEqual(['live-1', 'live-2'])
  })

  it('orders drafts newest first', async () => {
    fakeCms({
      unpublished: [
        doc('old', { publish_date: '2026-01-01' }),
        doc('new', { publish_date: '2026-09-30' }),
        doc('mid', { publish_date: '2026-05-01' }),
      ],
    })
    await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })
    expect(feedIds().slice(0, 3)).toEqual(['new', 'mid', 'old'])
  })

  it('adds nothing when the lens is prod, and does not even ask for drafts', async () => {
    const { calls } = fakeCms({ unpublished: [doc('d1')] })
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: LENS_PROD })

    expect(added).toEqual([])
    expect(feedIds()).toEqual(['live-1', 'live-2'])
    expect(calls.some((u) => u.includes('published=false'))).toBe(false)
  })

  it('shows only the unpublished posts that are in the chosen changeset', async () => {
    fakeCms({
      unpublished: [doc('in-cs'), doc('elsewhere')],
      changesets: {
        'cs-1': [
          { id: 'in-cs', doc_type: 'blog_post' },
          { id: 'live-1', doc_type: 'blog_post' }, // live: already has a card
          { id: 'a-project', doc_type: 'project_page' }, // another type
        ],
      },
      byId: { 'live-1': doc('live-1', {}, { published: true }), 'a-project': doc('a-project', {}, { doc_type: 'project_page' }) },
    })
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: changesetLens('cs-1') })

    expect(added.map((el) => el.dataset.cmsId)).toEqual(['in-cs'])
  })

  it('shows the draft title, not the published one, for an unpublished post that was edited', async () => {
    const stale = doc('d1', { title: 'As created' }, { has_draft: true })
    fakeCms({ unpublished: [stale], byId: { d1: doc('d1', { title: 'As edited' }, { has_draft: true }) } })
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })

    expect(added[0].querySelector('[data-cms-fill="title"]').textContent).toBe('As edited')
  })

  it('skips a post that is staged for deletion', async () => {
    fakeCms({ unpublished: [doc('going', {}, { draft_deleted: true }), doc('staying')] })
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })
    expect(added.map((el) => el.dataset.cmsId)).toEqual(['staying'])
  })

  it('does not add a second card for a post already on the page', async () => {
    fakeCms({ unpublished: [doc('d1')] })
    await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })

    expect(added).toEqual([])
    expect(document.querySelectorAll('[data-cms-id="d1"]')).toHaveLength(1)
  })

  it('drops drafts the lens no longer asks for, and keeps live cards', async () => {
    fakeCms({ unpublished: [doc('d1')] })
    await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })
    expect(feedIds()).toContain('d1')

    await syncDraftCards({ cmsBase: CMS, lens: LENS_PROD })
    expect(feedIds()).toEqual(['live-1', 'live-2'])
  })

  it('marks live posts that carry unpublished edits, whatever the lens', async () => {
    fakeCms({ edited: ['live-2'] })
    await syncDraftCards({ cmsBase: CMS, lens: LENS_PROD })

    expect(document.querySelector('[data-cms-id="live-2"] [data-cms-draft-pill="edited"]')).not.toBeNull()
    expect(document.querySelector('[data-cms-id="live-1"] [data-cms-draft-pill]')).toBeNull()
  })

  it('marks a live post once however often it runs', async () => {
    fakeCms({ edited: ['live-2'] })
    await syncDraftCards({ cmsBase: CMS, lens: LENS_PROD })
    await syncDraftCards({ cmsBase: CMS, lens: LENS_PROD })
    expect(document.querySelectorAll('[data-cms-id="live-2"] [data-cms-draft-pill]')).toHaveLength(1)
  })

  it('rejects when the CMS cannot be read, leaving the page as it was', async () => {
    fakeCms({ failList: true })
    await expect(syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })).rejects.toThrow()
    expect(feedIds()).toEqual(['live-1', 'live-2'])
  })

  it('does nothing on a page with no draft-capable list', async () => {
    document.body.innerHTML = '<article data-cms-id="solo"></article>'
    const { fetchMock } = fakeCms()
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })
    expect(added).toEqual([])
    expect(fetchMock).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// A feed that shows several document types
// ---------------------------------------------------------------------------

const definition = (id, body = {}, extra = {}) => ({
  id,
  doc_type: 'definition',
  slug: id,
  published: false,
  has_draft: false,
  draft_deleted: null,
  body: { term: `Term ${id}`, definition: `What ${id} means.`, personal_notes: `My take on ${id}.`, publish_date: '2026-09-15', ...body },
  ...extra,
})

/** One feed holding posts and definitions, with a card template for each. */
function mountMixedPage({ definitionTemplate = true } = {}) {
  document.body.innerHTML = `
    <div data-cms-list="blog_post definition" id="feed">
      <article data-cms-id="live-1" data-cms-type="blog_post"><span data-cms-field="title">Live</span></article>
      <article data-type="definition" id="live-def"><span>A live definition (not editable here)</span></article>
    </div>
    <template data-cms-draft-template="blog_post">
      <article class="log-record">
        <span data-cms-field="title" data-cms-fill="title"></span>
      </article>
    </template>
    ${definitionTemplate ? `<template data-cms-draft-template="definition">
      <article class="log-record" data-type="definition">
        <time data-cms-fill="publish_date" data-cms-fill-format="date"></time>
        <h2><span data-cms-fill="term"></span></h2>
        <blockquote><p data-cms-fill="definition" data-cms-fill-format="excerpt"></p></blockquote>
        <p data-cms-fill="personal_notes" data-cms-fill-format="excerpt"></p>
      </article>
    </template>` : ''}
  `
}

describe('a feed that shows several document types', () => {
  const draftIds = () => [...document.querySelectorAll('#feed [data-cms-draft-card]')].map((el) => el.dataset.cmsId)

  beforeEach(() => mountMixedPage())

  it('finds one slot per type that has a template', () => {
    const slots = findDraftSlots()
    expect(slots.map((s) => s.docType)).toEqual(['blog_post', 'definition'])
    expect(slots[0].list).toBe(slots[1].list)
  })

  it('ignores a type named by the feed that has no template', () => {
    mountMixedPage({ definitionTemplate: false })
    expect(findDraftSlots().map((s) => s.docType)).toEqual(['blog_post'])
  })

  it('draws a definition from its own template', async () => {
    fakeCms({ unpublished: [definition('d1')] })
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })

    expect(added).toHaveLength(1)
    const card = added[0]
    expect(card.dataset.cmsId).toBe('d1')
    expect(card.dataset.cmsType).toBe('definition')
    expect(card.querySelector('[data-cms-fill="term"]').textContent).toBe('Term d1')
    expect(card.querySelector('[data-cms-fill="definition"]').textContent).toBe('What d1 means.')
    expect(card.querySelector('[data-cms-fill="personal_notes"]').textContent).toBe('My take on d1.')
    expect(card.querySelector('time').textContent).toBe('September 15, 2026')
    expect(card.querySelector('[data-cms-draft-pill="draft"]')).not.toBeNull()
  })

  it('draws both types in one feed, each from its own template', async () => {
    fakeCms({ unpublished: [doc('p1'), definition('d1')] })
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })

    expect(added.map((el) => `${el.dataset.cmsType}:${el.dataset.cmsId}`).sort()).toEqual([
      'blog_post:p1',
      'definition:d1',
    ])
    expect(document.querySelector('[data-cms-id="p1"] [data-cms-fill="title"]').textContent).toBe('Title p1')
    expect(document.querySelector('[data-cms-id="d1"] [data-cms-fill="term"]').textContent).toBe('Term d1')
  })

  it('does not let one type\'s sync remove the other type\'s cards', async () => {
    fakeCms({ unpublished: [doc('p1'), definition('d1')] })
    await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })
    await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })

    expect(draftIds().sort()).toEqual(['d1', 'p1'])
  })

  it('drops both types when the lens no longer asks for them, and keeps the live cards', async () => {
    fakeCms({ unpublished: [doc('p1'), definition('d1')] })
    await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })
    await syncDraftCards({ cmsBase: CMS, lens: LENS_PROD })

    expect(draftIds()).toEqual([])
    expect(document.getElementById('live-def')).not.toBeNull()
    expect(document.querySelector('[data-cms-id="live-1"]')).not.toBeNull()
  })

  it('shows a definition that is in the chosen changeset, and not one that is not', async () => {
    fakeCms({
      unpublished: [definition('in-cs'), definition('elsewhere'), doc('post-elsewhere')],
      changesets: { 'cs-1': [{ id: 'in-cs', doc_type: 'definition' }] },
    })
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: changesetLens('cs-1') })

    expect(added.map((el) => el.dataset.cmsId)).toEqual(['in-cs'])
  })

  it('names an untitled definition rather than drawing an empty heading', async () => {
    fakeCms({ unpublished: [definition('d1', { term: '' })] })
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })
    expect(added[0].querySelector('[data-cms-fill="term"]').textContent).toBe('Untitled draft')
  })

  it('copes with a definition that has no personal notes', async () => {
    fakeCms({ unpublished: [definition('d1', { personal_notes: undefined })] })
    const { added } = await syncDraftCards({ cmsBase: CMS, lens: LENS_ALL })
    expect(added[0].querySelector('[data-cms-fill="personal_notes"]').textContent).toBe('')
  })
})
