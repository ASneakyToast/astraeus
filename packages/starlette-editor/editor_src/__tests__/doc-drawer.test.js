// @vitest-environment happy-dom

/**
 * Tests for components/doc-drawer.js — the document list as a small-screen drawer.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  isDocDrawerOpen,
  openDocDrawer,
  closeDocDrawer,
  toggleDocDrawer,
  wireDocDrawerDismiss,
} from '../components/doc-drawer.js'

beforeEach(() => {
  document.body.innerHTML = `
    <div class="sidebar-docs__backdrop"></div>
    <aside class="sidebar-types"></aside>
    <aside class="sidebar-docs"></aside>
  `
})

const drawer = () => document.querySelector('.sidebar-docs')
const backdrop = () => document.querySelector('.sidebar-docs__backdrop')

describe('open and close', () => {
  it('starts closed', () => {
    expect(isDocDrawerOpen()).toBe(false)
  })

  it('opens the drawer and its backdrop together', () => {
    openDocDrawer()

    expect(isDocDrawerOpen()).toBe(true)
    expect(backdrop().classList.contains('is-open')).toBe(true)
  })

  it('closes both again', () => {
    openDocDrawer()
    closeDocDrawer()

    expect(drawer().classList.contains('is-open')).toBe(false)
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
    expect(isDocDrawerOpen()).toBe(false)
  })
})

describe('dismissal', () => {
  it('closes on Escape', () => {
    const unwire = wireDocDrawerDismiss()
    openDocDrawer()

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

describe('missing shell', () => {
  it('does not throw when the drawer is not in the DOM', () => {
    document.body.innerHTML = ''

    expect(() => openDocDrawer()).not.toThrow()
    expect(isDocDrawerOpen()).toBe(false)
  })
})

describe('back gesture', () => {
  it('pushes a history entry so back dismisses the drawer, not the site', () => {
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

describe('both sidebars move as one panel', () => {
  it('opens the type list alongside the document list', () => {
    openDocDrawer()

    // Below 640px they are one navigation surface, not a rail plus a drawer.
    expect(document.querySelector('.sidebar-types').classList.contains('is-open')).toBe(true)
    expect(document.querySelector('.sidebar-docs').classList.contains('is-open')).toBe(true)
  })

  it('closes both', () => {
    openDocDrawer()
    closeDocDrawer()

    expect(document.querySelector('.sidebar-types').classList.contains('is-open')).toBe(false)
    expect(document.querySelector('.sidebar-docs').classList.contains('is-open')).toBe(false)
  })
})
