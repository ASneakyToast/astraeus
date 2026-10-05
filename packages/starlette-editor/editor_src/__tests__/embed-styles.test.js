// @vitest-environment jsdom
/**
 * The embed supplies its own copy of the design tokens and drawer/toast styles
 * (embed/styles.js) because the host site loads neither tokens.css nor
 * editor.css. These tests keep that copy honest and keep it from leaking into
 * the host's own styles.
 */

import { describe, it, expect, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  CHROME_CSS_TEXT,
  CHROME_SELECTORS,
  CHROME_TOKENS,
  injectChromeStyles,
} from '../embed/styles.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const TOKENS_CSS = readFileSync(
  join(HERE, '../../../starlette-cms/starlette_cms/static/tokens.css'),
  'utf8',
)

/** The first `:root { … }` block of tokens.css, as name → value. */
function rootTokens() {
  const block = TOKENS_CSS.split(':root {')[1].split('\n}')[0]
  const out = {}
  for (const m of block.matchAll(/^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);/gm)) out[m[1]] = m[2].trim()
  return out
}

afterEach(() => {
  document.head.innerHTML = ''
})

describe('embedded tokens', () => {
  const real = rootTokens()

  it.each(Object.entries(CHROME_TOKENS))('%s matches tokens.css', (name, value) => {
    expect(real[name], `${name} is not in tokens.css`).toBeDefined()
    expect(value).toBe(real[name])
  })

  it('covers every token the panels, drawer and toasts use', () => {
    const files = ['components/changeset-panel.js', 'components/chat-panel.js', 'components/toast.js']
    const used = new Set()
    for (const f of files) {
      const src = readFileSync(join(HERE, '..', f), 'utf8')
      for (const m of src.matchAll(/var\((--[a-z0-9-]+)\)/g)) used.add(m[1])
    }
    for (const m of CHROME_CSS_TEXT.matchAll(/var\((--[a-z0-9-]+)\)/g)) used.add(m[1])

    const missing = [...used].filter((name) => !(name in CHROME_TOKENS))
    expect(missing).toEqual([])
  })
})

describe('scoping', () => {
  /** Selectors of every rule outside @keyframes. */
  function ruleSelectors() {
    const css = CHROME_CSS_TEXT.replace(/\/\*[\s\S]*?\*\//g, '')
    const withoutKeyframes = css.replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})+[^{}]*\}/g, '')
    const selectors = []
    for (const m of withoutKeyframes.matchAll(/([^{}]+)\{[^{}]*\}/g)) {
      for (const sel of m[1].split(',')) selectors.push(sel.trim())
    }
    return selectors.filter(Boolean)
  }

  it('only styles the editor\'s own elements, never the host\'s', () => {
    const scopes = CHROME_SELECTORS
    const strays = ruleSelectors().filter((sel) => !scopes.some((scope) => sel.startsWith(scope)))
    expect(strays).toEqual([])
  })

  it('does not define :root variables, which would collide with the host\'s tokens', () => {
    expect(CHROME_CSS_TEXT).not.toMatch(/:root|\bhtml\b|\bbody\b/)
  })

  it('renames its keyframes so it cannot replace the host\'s', () => {
    const names = [...CHROME_CSS_TEXT.matchAll(/@keyframes\s+([\w-]+)/g)].map((m) => m[1])
    expect(names.length).toBeGreaterThan(0)
    expect(names.filter((n) => !n.startsWith('astraeus-'))).toEqual([])
  })

  it('puts the tokens on the panels, so their var() calls resolve', () => {
    const head = CHROME_CSS_TEXT.split('{')[0]
    for (const scope of CHROME_SELECTORS) expect(head).toContain(scope)
  })
})

describe('injectChromeStyles', () => {
  it('adds the stylesheet to the page', () => {
    injectChromeStyles()
    const style = document.getElementById('astraeus-embed-styles')
    expect(style).not.toBeNull()
    expect(style.textContent).toContain('--bg-elevated')
  })

  it('adds it once however often it is called', () => {
    injectChromeStyles()
    injectChromeStyles()
    expect(document.querySelectorAll('#astraeus-embed-styles')).toHaveLength(1)
  })
})
