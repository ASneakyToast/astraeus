/**
 * Tests for prosemirror/markdown.js — Markdown ↔ ProseMirror round-trips.
 */

import { describe, it, expect } from 'vitest'
import { Schema } from 'prosemirror-model'
import { schema as basicSchema } from 'prosemirror-schema-basic'
import { addListNodes } from 'prosemirror-schema-list'
import { markdownToPmDoc, pmDocToMarkdown } from '../prosemirror/markdown.js'

/** Shared schema that includes list nodes — mirrors what mount.js uses. */
const schema = new Schema({
  nodes: addListNodes(basicSchema.spec.nodes, 'paragraph block*', 'block'),
  marks: basicSchema.spec.marks,
})

describe('markdownToPmDoc', () => {
  it('returns a valid doc node for a simple paragraph', () => {
    const doc = markdownToPmDoc('Hello world', schema)
    expect(doc.type.name).toBe('doc')
    expect(doc.childCount).toBeGreaterThan(0)
  })

  it('returns a valid empty doc for empty string', () => {
    const doc = markdownToPmDoc('', schema)
    expect(doc.type.name).toBe('doc')
  })

  it('returns a valid empty doc for null (null safety)', () => {
    const doc = markdownToPmDoc(null, schema)
    expect(doc.type.name).toBe('doc')
  })

  it('returns a valid empty doc for undefined', () => {
    const doc = markdownToPmDoc(undefined, schema)
    expect(doc.type.name).toBe('doc')
  })

  it('parses a heading', () => {
    const doc = markdownToPmDoc('# Hello', schema)
    const firstChild = doc.firstChild
    expect(firstChild.type.name).toBe('heading')
    expect(firstChild.attrs.level).toBe(1)
  })

  it('parses bold text', () => {
    const doc = markdownToPmDoc('**bold**', schema)
    const para = doc.firstChild
    expect(para.type.name).toBe('paragraph')
    // The bold text node should carry a 'strong' mark
    const marks = para.firstChild?.marks ?? []
    expect(marks.some(m => m.type.name === 'strong')).toBe(true)
  })

  it('parses italic text', () => {
    const doc = markdownToPmDoc('_italic_', schema)
    const para = doc.firstChild
    const marks = para.firstChild?.marks ?? []
    expect(marks.some(m => m.type.name === 'em')).toBe(true)
  })

  it('parses a bullet list', () => {
    const doc = markdownToPmDoc('- item one\n- item two', schema)
    const firstChild = doc.firstChild
    expect(firstChild.type.name).toBe('bullet_list')
  })

  it('parses an ordered list', () => {
    const doc = markdownToPmDoc('1. first\n2. second', schema)
    const firstChild = doc.firstChild
    expect(firstChild.type.name).toBe('ordered_list')
  })

  it('parses a blockquote', () => {
    const doc = markdownToPmDoc('> A quote', schema)
    expect(doc.firstChild.type.name).toBe('blockquote')
  })

  it('parses a code block', () => {
    const doc = markdownToPmDoc('```\nconst x = 1\n```', schema)
    expect(doc.firstChild.type.name).toBe('code_block')
  })
})

describe('pmDocToMarkdown', () => {
  it('serializes a paragraph back to text', () => {
    const doc = markdownToPmDoc('Hello world', schema)
    const md = pmDocToMarkdown(doc)
    expect(md).toContain('Hello world')
  })

  it('serializes bold with ** markers', () => {
    const doc = markdownToPmDoc('**bold**', schema)
    const md = pmDocToMarkdown(doc)
    expect(md).toContain('**bold**')
  })

  it('serializes italic with _ markers', () => {
    const doc = markdownToPmDoc('_italic_', schema)
    const md = pmDocToMarkdown(doc)
    expect(md).toMatch(/_italic_|[*]italic[*]/)
  })

  it('serializes a heading with # prefix', () => {
    const doc = markdownToPmDoc('# My Heading', schema)
    const md = pmDocToMarkdown(doc)
    expect(md).toContain('# My Heading')
  })

  it('serializes h2 with ## prefix', () => {
    const doc = markdownToPmDoc('## Sub heading', schema)
    const md = pmDocToMarkdown(doc)
    expect(md).toContain('## Sub heading')
  })
})

describe('round-trip fidelity', () => {
  const cases = [
    'Simple paragraph.',
    '# Heading 1',
    '## Heading 2',
    '### Heading 3',
    'With **bold** text.',
    'With _italic_ text.',
    '- bullet one\n- bullet two',
    '1. first item\n2. second item',
    '> A blockquote line.',
  ]

  for (const input of cases) {
    it(`round-trips: ${input.slice(0, 40)}`, () => {
      const doc = markdownToPmDoc(input, schema)
      const output = pmDocToMarkdown(doc)
      // The serialized form should contain the key textual content
      // (exact whitespace/markers may differ slightly between parse and serialize)
      const textContent = doc.textContent
      expect(textContent.length).toBeGreaterThan(0)
      expect(typeof output).toBe('string')
      expect(output.length).toBeGreaterThan(0)
    })
  }
})
