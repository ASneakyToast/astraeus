// @vitest-environment jsdom
/**
 * Tests for the embed script modules.
 *
 * Tests focus on pure logic that can run without a real browser:
 *   - cmsBase derivation from URL string
 *   - EditToolbar state machine
 *   - activateField field-type detection
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ---------------------------------------------------------------------------
// cmsBase derivation
// ---------------------------------------------------------------------------

describe('cmsBase derivation from script src', () => {
  it('extracts origin from a full embed.js URL', () => {
    const src = 'https://cms.example.com/editor/embed.js'
    const url = new URL(src)
    expect(url.origin).toBe('https://cms.example.com')
  })

  it('extracts origin when path is just /embed.js', () => {
    const src = 'https://cms.joellithgow.com/embed.js'
    const url = new URL(src)
    expect(url.origin).toBe('https://cms.joellithgow.com')
  })

  it('handles non-standard port', () => {
    const src = 'http://localhost:8000/editor/embed.js'
    const url = new URL(src)
    expect(url.origin).toBe('http://localhost:8000')
  })

  it('returns null when scriptEl is null (defer/async context)', () => {
    // Simulate the guard: if scriptEl is null, cmsBase is null
    const scriptEl = null
    const scriptUrl = scriptEl ? new URL(scriptEl.src) : null
    const cmsBase = scriptUrl ? scriptUrl.origin : null
    expect(cmsBase).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// EditToolbar state machine
// ---------------------------------------------------------------------------

describe('EditToolbar', async () => {
  // We need a minimal DOM. Vitest uses jsdom by default.
  let EditToolbar

  beforeEach(async () => {
    // Dynamic import so the module can be re-evaluated if needed
    const mod = await import('../embed/toolbar.js')
    EditToolbar = mod.EditToolbar
    document.body.innerHTML = ''
  })

  afterEach(() => {
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  it('initial state is "viewing"', () => {
    const toolbar = new EditToolbar({ cmsBase: 'https://cms.example.com', cmsElements: [] })
    expect(toolbar.state).toBe('viewing')
  })

  it('mount() appends toolbar element to document.body', () => {
    const toolbar = new EditToolbar({ cmsBase: 'https://cms.example.com', cmsElements: [] })
    toolbar.mount()
    expect(document.getElementById('astraeus-toolbar')).not.toBeNull()
  })

  it('setState("editing") changes state and re-renders', () => {
    const toolbar = new EditToolbar({ cmsBase: 'https://cms.example.com', cmsElements: [] })
    toolbar.mount()
    toolbar.setState('editing')
    expect(toolbar.state).toBe('editing')
    // In editing state the toolbar should show Publish and Discard buttons
    const el = document.getElementById('astraeus-toolbar')
    expect(el.textContent).toContain('Publish')
    expect(el.textContent).toContain('Discard draft')
  })

  it('setState("saving") shows saving indicator', () => {
    const toolbar = new EditToolbar({ cmsBase: 'https://cms.example.com', cmsElements: [] })
    toolbar.mount()
    toolbar.setState('saving')
    expect(toolbar.state).toBe('saving')
    const el = document.getElementById('astraeus-toolbar')
    expect(el.textContent).toContain('Saving')
  })

  it('setState("publishing") shows publishing indicator', () => {
    const toolbar = new EditToolbar({ cmsBase: 'https://cms.example.com', cmsElements: [] })
    toolbar.mount()
    toolbar.setState('publishing')
    expect(toolbar.state).toBe('publishing')
    const el = document.getElementById('astraeus-toolbar')
    expect(el.textContent).toContain('Publishing')
  })

  it('setState("published") shows published indicator', () => {
    const toolbar = new EditToolbar({ cmsBase: 'https://cms.example.com', cmsElements: [] })
    toolbar.mount()
    toolbar.setState('published')
    expect(toolbar.state).toBe('published')
    const el = document.getElementById('astraeus-toolbar')
    expect(el.textContent).toContain('Published')
  })

  it('viewing state renders an Edit draft button', () => {
    const toolbar = new EditToolbar({ cmsBase: 'https://cms.example.com', cmsElements: [] })
    toolbar.mount()
    // viewing is initial state
    const el = document.getElementById('astraeus-toolbar')
    expect(el.textContent).toContain('Edit draft')
  })

  it('_publish() calls fetch with correct URL and sets state to published', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)

    const cmsBase = 'https://cms.example.com'
    const mockEl = { dataset: { cmsId: 'doc-123' } }
    const toolbar = new EditToolbar({ cmsBase, cmsElements: [mockEl] })
    toolbar.mount()
    toolbar.activeElement = mockEl
    toolbar.setState('editing')

    await toolbar._publish()

    expect(fetchMock).toHaveBeenCalledWith(
      `${cmsBase}/api/documents/doc-123/publish`,
      expect.objectContaining({ method: 'POST', credentials: 'include' })
    )
    expect(toolbar.state).toBe('published')
  })

  it('_discardDraft() calls fetch and reloads', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    const reloadMock = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { reload: reloadMock },
      writable: true,
    })

    const cmsBase = 'https://cms.example.com'
    const mockEl = { dataset: { cmsId: 'doc-456' } }
    const toolbar = new EditToolbar({ cmsBase, cmsElements: [mockEl] })
    toolbar.mount()
    toolbar.activeElement = mockEl

    await toolbar._discardDraft()

    expect(fetchMock).toHaveBeenCalledWith(
      `${cmsBase}/api/documents/doc-456/discard-draft`,
      expect.objectContaining({ method: 'POST', credentials: 'include' })
    )
    expect(reloadMock).toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// activateField — field type detection
// ---------------------------------------------------------------------------

describe('activateField field-type detection', async () => {
  const { activateField } = await import('../embed/edit-mode.js')

  beforeEach(() => {
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('detects ProseMirror JSON doc by type === "doc"', async () => {
    const pmDoc = { type: 'doc', content: [] }

    // Mock the dynamic import of prosemirror-embed
    vi.mock('../embed/prosemirror-embed.js', () => ({
      mountProseMirrorOnElement: vi.fn().mockResolvedValue(undefined),
    }))

    const el = document.createElement('div')
    document.body.appendChild(el)
    const toolbar = { setState: vi.fn() }

    // Should not throw — the mock handles the PM mount
    await expect(
      activateField(el, {
        fieldName: 'body',
        fieldValue: pmDoc,
        docId: 'doc-1',
        cmsBase: 'https://cms.example.com',
        toolbar,
      })
    ).resolves.toBeUndefined()
  })

  it('makes plain string fields contentEditable for heading tags', async () => {
    const el = document.createElement('h1')
    el.textContent = 'Original title'
    document.body.appendChild(el)
    const toolbar = { setState: vi.fn() }

    await activateField(el, {
      fieldName: 'title',
      fieldValue: 'Original title',
      docId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      toolbar,
    })

    expect(el.contentEditable).toBe('true')
  })

  it('makes plain string fields contentEditable for <p> tag', async () => {
    const el = document.createElement('p')
    el.textContent = 'Some text'
    document.body.appendChild(el)
    const toolbar = { setState: vi.fn() }

    await activateField(el, {
      fieldName: 'excerpt',
      fieldValue: 'Some text',
      docId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      toolbar,
    })

    expect(el.contentEditable).toBe('true')
  })

  it('does not activate a non-string value on a div (no-op)', async () => {
    const el = document.createElement('div')
    document.body.appendChild(el)
    const toolbar = { setState: vi.fn() }

    // fieldValue is a plain object but NOT a ProseMirror doc (no .type === "doc")
    await activateField(el, {
      fieldName: 'meta',
      fieldValue: { foo: 'bar' },
      docId: 'doc-1',
      cmsBase: 'https://cms.example.com',
      toolbar,
    })

    // Should be unmodified — contentEditable not set (jsdom returns undefined or "inherit")
    expect(el.contentEditable === 'inherit' || el.contentEditable === undefined).toBe(true)
  })
})
