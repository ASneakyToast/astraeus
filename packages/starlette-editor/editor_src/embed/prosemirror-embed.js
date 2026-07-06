/**
 * ProseMirror mounting for the embed script.
 *
 * Phase 3A: basic non-collab mount with debounced REST PATCH.
 * Phase 3B: will add WS collab plugin here.
 */
import { EditorState } from 'prosemirror-state'
import { EditorView } from 'prosemirror-view'
import { Schema } from 'prosemirror-model'
import { schema as basicSchema } from 'prosemirror-schema-basic'
import { addListNodes } from 'prosemirror-schema-list'
import { exampleSetup } from 'prosemirror-example-setup'

// Build a schema that includes lists
const pmSchema = new Schema({
  nodes: addListNodes(basicSchema.spec.nodes, 'paragraph block*', 'block'),
  marks: basicSchema.spec.marks,
})

export async function mountProseMirrorOnElement(el, { doc, docId, fieldName, cmsBase, toolbar }) {
  // Clear existing static HTML
  el.innerHTML = ''
  el.style.outline = '2px dashed rgba(37, 99, 235, 0.5)'
  el.style.minHeight = '100px'

  // Parse ProseMirror JSON doc into a ProseMirror Node
  let pmDoc
  try {
    pmDoc = pmSchema.nodeFromJSON(doc)
  } catch {
    // Fallback: empty doc
    pmDoc = pmSchema.node('doc', null, [pmSchema.node('paragraph')])
  }

  const state = EditorState.create({
    doc: pmDoc,
    plugins: exampleSetup({ schema: pmSchema, menuBar: false }),
  })

  let saveTimer
  const view = new EditorView(el, {
    state,
    dispatchTransaction(tr) {
      const newState = view.state.apply(tr)
      view.updateState(newState)

      if (!tr.docChanged) return

      // Debounced REST PATCH for Phase 3A (WS collab replaces this in Phase 3B)
      clearTimeout(saveTimer)
      toolbar.setState('saving')
      saveTimer = setTimeout(async () => {
        const pmJson = newState.doc.toJSON()
        await fetch(`${cmsBase}/api/documents/${docId}`, {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ body: { [fieldName]: pmJson } }),
        })
        toolbar.setState('editing')
      }, 800)
    },
  })

  // Store view reference for Phase 3B to upgrade to collab
  el._pmView = view
}
