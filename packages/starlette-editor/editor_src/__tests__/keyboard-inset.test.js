// @vitest-environment happy-dom

/**
 * Tests for components/keyboard-inset.js.
 *
 * The keyboard does not shrink the layout viewport, so fixed bottom chrome
 * sits under it. visualViewport reports the difference; this publishes it.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { wireKeyboardInset } from '../components/keyboard-inset.js'

/** Stand in for visualViewport, which happy-dom does not implement. */
function fakeViewport({ height, offsetTop = 0 }) {
  const listeners = {}
  return {
    height,
    offsetTop,
    addEventListener: (type, fn) => { (listeners[type] ??= []).push(fn) },
    removeEventListener: (type, fn) => {
      listeners[type] = (listeners[type] || []).filter(f => f !== fn)
    },
    emit: type => (listeners[type] || []).forEach(fn => fn()),
    listenerCount: type => (listeners[type] || []).length,
  }
}

const inset = () => document.documentElement.style.getPropertyValue('--keyboard-inset')

beforeEach(() => {
  window.innerHeight = 844
  document.documentElement.style.removeProperty('--keyboard-inset')
})

afterEach(() => {
  delete window.visualViewport
})

describe('with visualViewport', () => {
  it('reports no inset when the keyboard is closed', () => {
    window.visualViewport = fakeViewport({ height: 844 })

    const unwire = wireKeyboardInset()

    expect(inset()).toBe('0px')
    unwire()
  })

  it('reports the keyboard height when it opens', () => {
    const vv = fakeViewport({ height: 844 })
    window.visualViewport = vv
    const unwire = wireKeyboardInset()

    vv.height = 508
    vv.emit('resize')

    expect(inset()).toBe('336px')
    unwire()
  })

  it('does not mistake a scrolled-away URL bar for a keyboard', () => {
    // A shrunken viewport that is also offset is the page scrolling under
    // browser chrome, not the keyboard.
    const vv = fakeViewport({ height: 800, offsetTop: 44 })
    window.visualViewport = vv

    const unwire = wireKeyboardInset()

    expect(inset()).toBe('0px')
    unwire()
  })

  it('returns to zero when the keyboard closes', () => {
    const vv = fakeViewport({ height: 508 })
    window.visualViewport = vv
    const unwire = wireKeyboardInset()
    expect(inset()).toBe('336px')

    vv.height = 844
    vv.emit('resize')

    expect(inset()).toBe('0px')
    unwire()
  })

  it('tracks viewport scrolls as well as resizes', () => {
    const vv = fakeViewport({ height: 844 })
    window.visualViewport = vv
    const unwire = wireKeyboardInset()

    vv.height = 600
    vv.emit('scroll')

    expect(inset()).toBe('244px')
    unwire()
  })

  it('detaches and clears on unwire', () => {
    const vv = fakeViewport({ height: 508 })
    window.visualViewport = vv

    wireKeyboardInset()()

    expect(vv.listenerCount('resize')).toBe(0)
    expect(inset()).toBe('')
  })
})

describe('without visualViewport', () => {
  it('is a no-op rather than an error', () => {
    expect(() => wireKeyboardInset()()).not.toThrow()
    expect(inset()).toBe('')
  })
})
