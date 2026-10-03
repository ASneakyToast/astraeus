/**
 * Generate step fixtures for the Python conformance test (ADR 024, T12).
 *
 * Builds steps with the editor's own prosemirror-transform and schema, then
 * records the document each batch should produce. The Python side
 * (`starlette-cms/tests/test_collab_conformance.py`) must reach the same
 * document with `prosemirror-py`.
 *
 *   cd packages/starlette-editor && bun install && node scripts/gen-collab-fixtures.mjs
 */
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { EditorState, TextSelection, NodeSelection } from 'prosemirror-state'
import { toggleMark, setBlockType, wrapIn, lift } from 'prosemirror-commands'
import { wrapInList, splitListItem, liftListItem, sinkListItem } from 'prosemirror-schema-list'
import { schemaWithLists as schema } from '../editor_src/prosemirror/schema.js'

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(here, '../../starlette-cms/tests/fixtures/collab_steps.json')
const versionOf = (pkg) =>
  JSON.parse(readFileSync(resolve(here, '../node_modules', pkg, 'package.json'), 'utf8')).version

const p = (text, marks) =>
  ({ type: 'paragraph', content: text ? [{ type: 'text', text, ...(marks ? { marks } : {}) }] : undefined })
const doc = (...blocks) => ({ type: 'doc', content: blocks })

function stateFor(docJSON, selection) {
  const d = schema.nodeFromJSON(docJSON)
  let state = EditorState.create({ doc: d, schema })
  if (selection) {
    const [from, to = from] = selection
    state = state.apply(state.tr.setSelection(TextSelection.create(state.doc, from, to)))
  }
  return state
}

/** Run a command against a state and collect the steps it produced. */
function viaCommand(name, docJSON, selection, command) {
  const state = stateFor(docJSON, selection)
  let tr = null
  const ok = command(state, (t) => { tr = t })
  if (!ok || !tr) throw new Error(`command did not apply: ${name}`)
  return { name, start: docJSON, steps: tr.steps.map((s) => s.toJSON()), end: tr.doc.toJSON() }
}

/** Build a batch with a plain transform callback. */
function viaTransform(name, docJSON, build) {
  const state = stateFor(docJSON)
  const tr = state.tr
  build(tr, state)
  if (!tr.steps.length) throw new Error(`no steps: ${name}`)
  return { name, start: docJSON, steps: tr.steps.map((s) => s.toJSON()), end: tr.doc.toJSON() }
}

const hello = doc(p('Hello world'))
const two = doc(p('First paragraph'), p('Second paragraph'))
const quote = doc({ type: 'blockquote', content: [p('Roses are red'), p('Violets are blue')] })
const list = doc({ type: 'bullet_list', content: [
  { type: 'list_item', content: [p('one')] },
  { type: 'list_item', content: [p('two')] },
] })

const cases = [
  viaTransform('insert text', hello, (tr) => tr.insertText('!', 12)),
  viaTransform('delete range', hello, (tr) => tr.delete(1, 7)),
  viaTransform('replace text', hello, (tr) => tr.insertText('there', 7, 12)),
  viaTransform('split paragraph', hello, (tr) => tr.split(6)),
  viaTransform('join paragraphs', two, (tr) => tr.join(17)),
  viaTransform('autocorrect batch (delete, insert, mark)', doc(p('teh cat')), (tr, st) => {
    tr.delete(1, 4)
    tr.insertText('the', 1)
    tr.addMark(1, 4, schema.marks.em.create())
  }),
  viaTransform('add strong', hello, (tr) => tr.addMark(1, 6, schema.marks.strong.create())),
  viaTransform('add link with attrs', hello, (tr) =>
    tr.addMark(1, 6, schema.marks.link.create({ href: 'https://example.com', title: 'Example' }))),
  viaTransform('remove mark', doc(p('Hello', [{ type: 'strong' }])), (tr) =>
    tr.removeMark(1, 6, schema.marks.strong)),
  viaTransform('insert hard break', hello, (tr) => tr.replaceSelectionWith(schema.nodes.hard_break.create()).setSelection(TextSelection.create(tr.doc, 1))),
  viaTransform('insert image', hello, (tr) =>
    tr.insert(1, schema.nodes.image.create({ src: 'https://example.com/a.png', alt: 'a' }))),
  viaTransform('insert horizontal rule', two, (tr) => tr.insert(17, schema.nodes.horizontal_rule.create())),
  viaTransform('set heading level (attr step)', doc({ type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'Title' }] }),
    (tr) => tr.setNodeAttribute(0, 'level', 3)),
  viaCommand('paragraph to heading', hello, [3], setBlockType(schema.nodes.heading, { level: 2 })),
  viaCommand('wrap in blockquote', two, [3], wrapIn(schema.nodes.blockquote)),
  viaCommand('lift out of blockquote', quote, [3], lift),
  viaCommand('wrap in bullet list', two, [3, 22], wrapInList(schema.nodes.bullet_list)),
  viaCommand('wrap in ordered list', two, [3], wrapInList(schema.nodes.ordered_list)),
  viaCommand('split list item', list, [6], splitListItem(schema.nodes.list_item)),
  viaCommand('sink list item', list, [13], sinkListItem(schema.nodes.list_item)),
  viaCommand('lift list item', list, [6], liftListItem(schema.nodes.list_item)),
  viaTransform('replace across paragraphs', two, (tr) => tr.delete(5, 25)),
  viaTransform('code block text', doc({ type: 'code_block', content: [{ type: 'text', text: 'x = 1' }] }),
    (tr) => tr.insertText(' + 2', 6)),
]

mkdirSync(dirname(out), { recursive: true })
writeFileSync(out, JSON.stringify({
  generatedWith: {
    'prosemirror-transform': versionOf('prosemirror-transform'),
    'prosemirror-model': versionOf('prosemirror-model'),
  },
  cases,
}, null, 2) + '\n')
console.log(`wrote ${cases.length} cases to ${out}`)
