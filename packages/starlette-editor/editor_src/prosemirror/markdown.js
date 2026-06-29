/**
 * prosemirror/markdown.js — Markdown ↔ ProseMirror document serialisation.
 *
 * Uses prosemirror-markdown (markdown-it based) for proper block and inline
 * rendering — headings, bold, italic, lists, code fences, blockquotes, etc.
 */

import markdownit from 'markdown-it'
import { MarkdownParser, MarkdownSerializer, defaultMarkdownParser, defaultMarkdownSerializer } from 'prosemirror-markdown'

/**
 * Parse a Markdown string into a ProseMirror document node.
 *
 * Uses prosemirror-markdown (markdownit-based) for proper block and inline
 * rendering — headings, **bold**, _italic_, lists, code fences, blockquotes.
 *
 * @param {string|null|undefined} markdown
 * @param {import('prosemirror-model').Schema} schema
 * @returns {import('prosemirror-model').Node}
 */
export function markdownToPmDoc(markdown, schema) {
  const parser = new MarkdownParser(schema, markdownit(), defaultMarkdownParser.tokens)
  return parser.parse(markdown ?? '')
}

/**
 * Serialize a ProseMirror document to a Markdown string.
 *
 * Produces proper **bold**, _italic_, # heading, - list, ``` code fence, etc.
 *
 * @param {import('prosemirror-model').Node} doc
 * @returns {string}
 */
export function pmDocToMarkdown(doc) {
  return defaultMarkdownSerializer.serialize(doc)
}
