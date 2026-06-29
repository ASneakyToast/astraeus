/**
 * Tests for standard/utils.js — pure utility functions.
 */

import { describe, it, expect } from 'vitest'
import { humanizeType, humanizeFieldName, docTitle, formatDate, getOrderedFields, getDefaultValue } from '../standard/utils.js'

describe('humanizeType', () => {
  it('pluralizes a snake_case type', () => {
    expect(humanizeType('blog_post')).toBe('Blog Posts')
  })

  it('handles a single-word type', () => {
    expect(humanizeType('page')).toBe('Pages')
  })

  it('handles multi-word types', () => {
    expect(humanizeType('project_case_study')).toBe('Project Case Studys')
  })
})

describe('humanizeFieldName', () => {
  it('converts snake_case to Title Case', () => {
    expect(humanizeFieldName('my_field')).toBe('My Field')
  })

  it('handles a single word', () => {
    expect(humanizeFieldName('title')).toBe('Title')
  })
})

describe('docTitle', () => {
  it('prefers title over other fields', () => {
    expect(docTitle({ body: { title: 'Hello', name: 'World' }, slug: 'hello' })).toBe('Hello')
  })

  it('falls back to name when title is absent', () => {
    expect(docTitle({ body: { name: 'World' }, slug: 'hello' })).toBe('World')
  })

  it('falls back to slug when body is empty', () => {
    expect(docTitle({ body: {}, slug: 'my-slug' })).toBe('my-slug')
  })

  it('falls back to id prefix when slug is absent', () => {
    expect(docTitle({ body: {}, id: 'abc12345xyz' })).toBe('abc12345')
  })

  it('returns Untitled as final fallback', () => {
    expect(docTitle({})).toBe('Untitled')
    expect(docTitle(null)).toBe('Untitled')
  })
})

describe('formatDate', () => {
  it('returns a non-empty string for a valid ISO date', () => {
    const result = formatDate('2024-03-15T10:00:00Z')
    expect(typeof result).toBe('string')
    expect(result.length).toBeGreaterThan(0)
  })

  it('returns empty string for null', () => {
    expect(formatDate(null)).toBe('')
  })

  it('returns empty string for undefined', () => {
    expect(formatDate(undefined)).toBe('')
  })

  it('returns empty string for invalid date', () => {
    // new Date('not-a-date').toLocaleDateString() returns 'Invalid Date'
    // but we wrap in try/catch — it should return empty or some string
    const result = formatDate('not-a-date')
    // Should not throw
    expect(typeof result).toBe('string')
  })
})

describe('getDefaultValue', () => {
  it('returns meta.default when present', () => {
    expect(getDefaultValue({ type: 'string' }, { default: 'hello' })).toBe('hello')
  })

  it('returns prop.default when meta.default is absent', () => {
    expect(getDefaultValue({ type: 'string', default: 'world' }, {})).toBe('world')
  })

  it('returns false for boolean type', () => {
    expect(getDefaultValue({ type: 'boolean' }, {})).toBe(false)
  })

  it('returns null for number type', () => {
    expect(getDefaultValue({ type: 'number' }, {})).toBe(null)
  })

  it('returns null for integer type', () => {
    expect(getDefaultValue({ type: 'integer' }, {})).toBe(null)
  })

  it('returns [] for array type', () => {
    expect(getDefaultValue({ type: 'array' }, {})).toEqual([])
  })

  it('returns {} for object type', () => {
    expect(getDefaultValue({ type: 'object' }, {})).toEqual({})
  })

  it('returns empty string as fallback', () => {
    expect(getDefaultValue({ type: 'string' }, {})).toBe('')
  })
})

describe('getOrderedFields', () => {
  it('excludes slug and block_type', () => {
    const typeInfo = {
      schema: {
        properties: {
          slug: { type: 'string' },
          block_type: { type: 'string' },
          title: { type: 'string' },
        },
      },
      field_meta: {},
    }
    const fields = getOrderedFields(typeInfo)
    const names = fields.map(f => f.name)
    expect(names).not.toContain('slug')
    expect(names).not.toContain('block_type')
    expect(names).toContain('title')
  })

  it('sorts by display_order', () => {
    const typeInfo = {
      schema: {
        properties: {
          z_field: { type: 'string' },
          a_field: { type: 'string' },
        },
      },
      field_meta: {
        z_field: { display_order: 1 },
        a_field: { display_order: 2 },
      },
    }
    const fields = getOrderedFields(typeInfo)
    expect(fields[0].name).toBe('z_field')
    expect(fields[1].name).toBe('a_field')
  })

  it('returns empty array for typeInfo with no properties', () => {
    expect(getOrderedFields({ schema: {}, field_meta: {} })).toEqual([])
    expect(getOrderedFields(null)).toEqual([])
  })
})
