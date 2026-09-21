// @vitest-environment happy-dom

/**
 * Tests for components/doc-drawer.js — navigation as a route stack.
 *
 * State lives in classes on <body> rather than in transforms, because every
 * earlier version put the geometry in a transform that silently landed in the
 * wrong place. jsdom has no layout engine, so nothing here can catch that —
 * these cover the state machine, and the rendered result is checked visually.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  isDocDrawerOpen,
  openDocDrawer,
  closeDocDrawer,
  showDocRoute,
  showTypeRoute,
  toggleDocDrawer,
  wireDocDrawerDismiss,
} from '../components/doc-drawer.js'

beforeEach(() => {
  document.body.className = ''
  document.body.innerHTML = '<div class="sidebar-docs__backdrop"></div>'
})

const onDocRoute = () => document.body.classList.contains('nav-docs')
const backdrop = () => document.querySelector('.sidebar-docs__backdrop')

describe('opening and closing', () => {
  it('starts closed', () => {
    expect(isDocDrawerOpen()).toBe(false)
  })

  it('opens with the backdrop', () => {
    openDocDrawer()

    expect(isDocDrawerOpen()).toBe(true)
    expect(backdrop().classList.contains('is-open')).toBe(true)
  })

  it('opens on the type route when nothing is selected', () => {
    openDocDrawer({ activeType: null })

    expect(onDocRoute()).toBe(false)
  })

  it('opens straight to documents when a type is already selected', () => {
    openDocDrawer({ activeType: 'blog_post' })

    expect(onDocRoute()).toBe(true)
  })

  it('closes and clears the route', () => {
    openDocDrawer({ activeType: 'blog_post' })
    closeDocDrawer()

    expect(isDocDrawerOpen()).toBe(false)
    expect(onDocRoute()).toBe(false)
    expect(backdrop().classList.contains('is-open')).toBe(false)
  })

  it('toggles', () => {
    toggleDocDrawer()
    expect(isDocDrawerOpen()).toBe(true)

    toggleDocDrawer()
    expect(isDocDrawerOpen()).toBe(false)
  })

  it('closing an already-closed drawer is harmless', () => {
    expect(() => closeDocDrawer()).not.toThrow()
  })

  it('does not throw when the backdrop is absent', () => {
    document.body.innerHTML = ''

    expect(() => openDocDrawer()).not.toThrow()
    expect(isDocDrawerOpen()).toBe(true)
  })
})

describe('moving between routes', () => {
  it('advances to documents', () => {
    openDocDrawer()
    showDocRoute()

    expect(onDocRoute()).toBe(true)
  })

  it('goes back to types without closing navigation', () => {
    openDocDrawer({ activeType: 'blog_post' })
    showTypeRoute()

    expect(onDocRoute()).toBe(false)
    expect(isDocDrawerOpen()).toBe(true)
  })
})

describe('dismissal', () => {
  it('Escape steps back to types before closing', () => {
    const unwire = wireDocDrawerDismiss()
    openDocDrawer({ activeType: 'blog_post' })

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(onDocRoute()).toBe(false)
    expect(isDocDrawerOpen()).toBe(true)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(isDocDrawerOpen()).toBe(false)

    unwire()
  })

  it('ignores other keys', () => {
    const unwire = wireDocDrawerDismiss()
    openDocDrawer()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }))

    expect(isDocDrawerOpen()).toBe(true)
    unwire()
  })

  it('stops listening once unwired', () => {
    const unwire = wireDocDrawerDismiss()
    unwire()
    openDocDrawer()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

    expect(isDocDrawerOpen()).toBe(true)
  })
})

describe('back gesture', () => {
  it('pushes a history entry so back dismisses navigation, not the site', () => {
    const push = vi.spyOn(history, 'pushState')

    openDocDrawer()

    expect(push).toHaveBeenCalledWith({ docDrawer: true }, '')
    push.mockRestore()
  })

  it('does not stack entries when already open', () => {
    const push = vi.spyOn(history, 'pushState')

    openDocDrawer()
    openDocDrawer()

    expect(push).toHaveBeenCalledTimes(1)
    push.mockRestore()
  })

  it('closes on popstate', () => {
    const unwire = wireDocDrawerDismiss()
    openDocDrawer()

    window.dispatchEvent(new PopStateEvent('popstate'))

    expect(isDocDrawerOpen()).toBe(false)
    unwire()
  })

  it('does not pop again when the close came from history', () => {
    const back = vi.spyOn(history, 'back')
    const unwire = wireDocDrawerDismiss()
    openDocDrawer()

    window.dispatchEvent(new PopStateEvent('popstate'))

    expect(back).not.toHaveBeenCalled()
    back.mockRestore()
    unwire()
  })
})
