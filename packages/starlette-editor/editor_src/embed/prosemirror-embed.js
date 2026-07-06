/**
 * ProseMirror mounting for the embed script.
 *
 * Phase 3B: WS collab via prosemirror-collab — replaces the debounced REST
 * PATCH from Phase 3A. Steps are streamed to the CMS WebSocket authority;
 * the debounced PATCH path is removed for PM (rich text) fields.
 *
 * Plain text fields (h1–h6, p, span) still use debounced PATCH via edit-mode.js.
 */
import { EditorState } from 'prosemirror-state'
import { EditorView } from 'prosemirror-view'
import { Schema } from 'prosemirror-model'
import { schema as basicSchema } from 'prosemirror-schema-basic'
import { addListNodes } from 'prosemirror-schema-list'
import { exampleSetup } from 'prosemirror-example-setup'
import { collab } from 'prosemirror-collab'
import { CollabConnection } from './collab.js'

// Build a schema that includes lists
const pmSchema = new Schema({
  nodes: addListNodes(basicSchema.spec.nodes, 'paragraph block*', 'block'),
  marks: basicSchema.spec.marks,
})

function generateClientID() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

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

  const clientID = generateClientID()

  // Mount PM with collab plugin — version 0 initially, updated on WS init
  let collabConn = null

  const state = EditorState.create({
    doc: pmDoc,
    plugins: [
      ...exampleSetup({ schema: pmSchema, menuBar: false }),
      collab({ version: 0, clientID }),
    ],
  })

  const view = new EditorView(el, {
    state,
    dispatchTransaction(tr) {
      const newState = view.state.apply(tr)
      view.updateState(newState)
      // Notify collab connection to send pending steps
      if (collabConn && tr.docChanged) {
        collabConn.onTransaction()
      }
    },
  })

  // Start collab connection — will sync version on first WS init message
  collabConn = new CollabConnection({
    view,
    schema: pmSchema,
    documentId: docId,
    cmsBase,
    initialVersion: 0,
    toolbar,
    clientID,
  })

  // Store refs for cleanup
  el._pmView = view
  el._collabConn = collabConn

  // When toolbar reaches "published" state, destroy the WS connection
  const origSetState = toolbar.setState.bind(toolbar)
  toolbar.setState = (s) => {
    origSetState(s)
    if (s === 'published' && collabConn) {
      collabConn.destroy()
    }
  }
}
