/**
 * Tests for components/block-canvas.js — block management functions.
 * These functions mutate state.formData, so we reset it between tests.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { getBlockTypesMeta, addBlock, removeBlock, moveBlock } from '../components/block-canvas.js'
import { state } from '../state.js'

/** Minimal render noop. */
const noop = () => {}

/** Reset formData before each test. */
beforeEach(() => {
  state.formData = {}
  state.isDirty = false
  // Stub document.getElementById so updateBlockField doesn't throw
  if (typeof document === 'undefined') return
})

describe('getBlockTypesMeta', () => {
  it('resolves a homogeneous $ref list', () => {
    const prop = {
      type: 'array',
      items: { $ref: '#/$defs/HeroBlock' },
    }
    const typeSchema = {
      $defs: {
        HeroBlock: {
          properties: {
            block_type: { const: 'hero' },
            title: { type: 'string' },
          },
        },
      },
    }
    const result = getBlockTypesMeta(prop, typeSchema)
    expect(result).toHaveLength(1)
    expect(result[0].registeredType).toBe('hero')
    expect(result[0].name).toBe('HeroBlock')
  })

  it('resolves a polymorphic anyOf list', () => {
    const prop = {
      type: 'array',
      items: {
        anyOf: [
          { $ref: '#/$defs/HeroBlock' },
          { $ref: '#/$defs/TextBlock' },
        ],
      },
    }
    const typeSchema = {
      $defs: {
        HeroBlock: { properties: { block_type: { const: 'hero' } } },
        TextBlock: { properties: { block_type: { const: 'text' } } },
      },
    }
    const result = getBlockTypesMeta(prop, typeSchema)
    expect(result).toHaveLength(2)
    expect(result.map(r => r.registeredType)).toEqual(['hero', 'text'])
  })

  it('returns an empty array when items is missing', () => {
    expect(getBlockTypesMeta({}, {})).toEqual([])
    expect(getBlockTypesMeta({ items: null }, {})).toEqual([])
  })

  it('handles an inline (non-$ref) schema', () => {
    const prop = {
      type: 'array',
      items: {
        properties: { title: { type: 'string' } },
      },
    }
    const result = getBlockTypesMeta(prop, {})
    expect(result).toHaveLength(1)
    expect(result[0].registeredType).toBe('block')
  })
})

describe('addBlock', () => {
  it('appends a block with correct block_type and defaults', () => {
    const typeInfo = {
      registeredType: 'hero',
      schema: {
        properties: {
          block_type: { const: 'hero' },
          title: { type: 'string' },
          featured: { type: 'boolean' },
          count: { type: 'integer' },
        },
      },
    }
    addBlock('blocks', typeInfo, noop)
    expect(state.formData.blocks).toHaveLength(1)
    expect(state.formData.blocks[0].block_type).toBe('hero')
    expect(state.formData.blocks[0].title).toBe('')
    expect(state.formData.blocks[0].featured).toBe(false)
    expect(state.formData.blocks[0].count).toBe(null)
  })

  it('appends to an existing array', () => {
    state.formData.blocks = [{ block_type: 'existing' }]
    const typeInfo = { registeredType: 'new', schema: { properties: {} } }
    addBlock('blocks', typeInfo, noop)
    expect(state.formData.blocks).toHaveLength(2)
    expect(state.formData.blocks[1].block_type).toBe('new')
  })

  it('sets isDirty to true', () => {
    const typeInfo = { registeredType: 'x', schema: { properties: {} } }
    addBlock('blocks', typeInfo, noop)
    expect(state.isDirty).toBe(true)
  })
})

describe('removeBlock', () => {
  it('removes the block at the given index', () => {
    state.formData.blocks = [
      { block_type: 'a' },
      { block_type: 'b' },
      { block_type: 'c' },
    ]
    removeBlock('blocks', 1, noop)
    expect(state.formData.blocks).toHaveLength(2)
    expect(state.formData.blocks.map(b => b.block_type)).toEqual(['a', 'c'])
  })

  it('removes the first block', () => {
    state.formData.blocks = [{ block_type: 'a' }, { block_type: 'b' }]
    removeBlock('blocks', 0, noop)
    expect(state.formData.blocks.map(b => b.block_type)).toEqual(['b'])
  })

  it('removes the last block', () => {
    state.formData.blocks = [{ block_type: 'a' }, { block_type: 'b' }]
    removeBlock('blocks', 1, noop)
    expect(state.formData.blocks.map(b => b.block_type)).toEqual(['a'])
  })

  it('sets isDirty to true', () => {
    state.formData.blocks = [{ block_type: 'a' }]
    removeBlock('blocks', 0, noop)
    expect(state.isDirty).toBe(true)
  })
})

describe('moveBlock', () => {
  it('moves a block forward in the array', () => {
    state.formData.blocks = [
      { block_type: 'a' },
      { block_type: 'b' },
      { block_type: 'c' },
    ]
    moveBlock('blocks', 0, 2, noop)
    expect(state.formData.blocks.map(b => b.block_type)).toEqual(['b', 'c', 'a'])
  })

  it('moves a block backward in the array', () => {
    state.formData.blocks = [
      { block_type: 'a' },
      { block_type: 'b' },
      { block_type: 'c' },
    ]
    moveBlock('blocks', 2, 0, noop)
    expect(state.formData.blocks.map(b => b.block_type)).toEqual(['c', 'a', 'b'])
  })

  it('is a no-op when fromIndex === toIndex', () => {
    state.formData.blocks = [{ block_type: 'a' }, { block_type: 'b' }]
    moveBlock('blocks', 1, 1, noop)
    expect(state.formData.blocks.map(b => b.block_type)).toEqual(['a', 'b'])
  })

  it('sets isDirty to true after a real move', () => {
    state.formData.blocks = [{ block_type: 'a' }, { block_type: 'b' }]
    moveBlock('blocks', 0, 1, noop)
    expect(state.isDirty).toBe(true)
  })
})
