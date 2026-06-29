/**
 * Tests for standard/fields.js — field widget dispatch.
 */

import { describe, it, expect } from 'vitest'
import { fieldWidget } from '../standard/fields.js'

describe('fieldWidget dispatch table', () => {
  it('rich_text field_type → prosemirror', () => {
    expect(fieldWidget('body', { type: 'object' }, { field_type: 'rich_text' })).toBe('prosemirror')
  })

  it('block_list field_type → block_canvas', () => {
    expect(fieldWidget('blocks', { type: 'array' }, { field_type: 'block_list' })).toBe('block_canvas')
  })

  it('block field_type → block_canvas', () => {
    expect(fieldWidget('hero', { type: 'object' }, { field_type: 'block' })).toBe('block_canvas')
  })

  it('image field_type → image_picker', () => {
    expect(fieldWidget('cover_image', { type: 'string' }, { field_type: 'image' })).toBe('image_picker')
  })

  it('select field_type → select', () => {
    expect(fieldWidget('status', { type: 'string' }, { field_type: 'select' })).toBe('select')
  })

  it('boolean field_type → boolean', () => {
    expect(fieldWidget('is_featured', { type: 'boolean' }, { field_type: 'boolean' })).toBe('boolean')
  })

  it('number field_type → number', () => {
    expect(fieldWidget('price', { type: 'number' }, { field_type: 'number' })).toBe('number')
  })

  it('json field_type → json', () => {
    expect(fieldWidget('metadata', { type: 'object' }, { field_type: 'json' })).toBe('json')
  })

  it('document_ref field_type → input', () => {
    expect(fieldWidget('author', { type: 'string' }, { field_type: 'document_ref' })).toBe('input')
  })

  it('choices in meta → select (legacy heuristic)', () => {
    expect(fieldWidget('category', { type: 'string' }, { choices: ['a', 'b'] })).toBe('select')
  })

  it('boolean prop type → boolean', () => {
    expect(fieldWidget('active', { type: 'boolean' }, {})).toBe('boolean')
  })

  it('number prop type → number', () => {
    expect(fieldWidget('count', { type: 'number' }, {})).toBe('number')
  })

  it('integer prop type → number', () => {
    expect(fieldWidget('count', { type: 'integer' }, {})).toBe('number')
  })

  it('object prop type → json', () => {
    expect(fieldWidget('data', { type: 'object' }, {})).toBe('json')
  })

  it('array prop type → json', () => {
    expect(fieldWidget('tags', { type: 'array' }, {})).toBe('json')
  })

  it('long-name string → textarea', () => {
    expect(fieldWidget('body', { type: 'string' }, {})).toBe('textarea')
    expect(fieldWidget('description', { type: 'string' }, {})).toBe('textarea')
    expect(fieldWidget('overview', { type: 'string' }, {})).toBe('textarea')
    expect(fieldWidget('summary', { type: 'string' }, {})).toBe('textarea')
  })

  it('name containing markdown → prosemirror', () => {
    expect(fieldWidget('body_markdown', { type: 'string' }, {})).toBe('prosemirror')
    expect(fieldWidget('intro_markdown', { type: 'string' }, {})).toBe('prosemirror')
  })

  it('default string → input', () => {
    expect(fieldWidget('title', { type: 'string' }, {})).toBe('input')
    expect(fieldWidget('author', { type: 'string' }, {})).toBe('input')
  })
})
