/**
 * prosemirror/mount.js — Mount and destroy ProseMirror editor instances.
 */

import { EditorState } from 'prosemirror-state'
import { EditorView } from 'prosemirror-view'
import { Schema } from 'prosemirror-model'
import { schema as basicSchema } from 'prosemirror-schema-basic'
import { addListNodes } from 'prosemirror-schema-list'
import { exampleSetup } from 'prosemirror-example-setup'

import { collab } from 'prosemirror-collab'
import { CollabConnection } from '../embed/collab.js'
import { markdownToPmDoc, pmDocToMarkdown } from './markdown.js'
import { execPmCommand, updateToolbarState } from './toolbar.js'
import { fieldWidget } from '../standard/fields.js'
import { state } from '../state.js'

/**
 * Build a schema that includes list nodes (extends the basic schema).
 * Created once and reused for all PM instances.
 */
export const schemaWithLists = new Schema({
  nodes: addListNodes(basicSchema.spec.nodes, 'paragraph block*', 'block'),
  marks: basicSchema.spec.marks,
})

/**
 * Stub toolbar that satisfies CollabConnection's interface for the shell.
 * Peer presence and AI editing animations are no-ops here for now.
 */
function _makeCollabToolbarShim() {
  return {
    setState(s) {
      // Update dirty dot: 'saving' → show spinner class, 'editing' → clear
      const dot = document.getElementById('dirty-dot')
      if (dot) dot.classList.toggle('is-saving', s === 'saving')
    },
    updatePeers() {},   // no peer presence display in shell (yet)
    setAiEditing() {},  // no AI pulse in shell (yet)
  }
}

/**
 * Mount ProseMirror on all .pm-editor placeholder elements in the form.
 *
 * @param {Array<{name: string, prop: object, meta: object}>} fields
 * @param {function} onFieldChange
 * @param {{ cmsBase?: string, docId?: string, apiKey?: string }} [opts]
 */
export async function mountProseMirrorEditors(fields, onFieldChange, { cmsBase, docId, apiKey } = {}) {
  const pmFields = fields.filter(({ name, prop, meta }) => fieldWidget(name, prop, meta) === 'prosemirror');
  if (!pmFields.length) return;

  // Destroy any existing PM instances for this render cycle
  destroyPmInstances();

  for (const { name } of pmFields) {
    const mountEl = document.getElementById(`pm-mount-${name}`);
    if (!mountEl) continue;

    const fieldMeta = (state.schema?.[state.activeType]?.field_meta || {})[name] || {};

    const rawValue = state.formData[name];
    // If the stored value is already a ProseMirror JSON doc object (RichTextField),
    // restore it directly; otherwise fall back to the markdown parse path.
    let doc;
    if (rawValue && typeof rawValue === 'object' && rawValue.type === 'doc') {
      try {
        doc = schemaWithLists.nodeFromJSON(rawValue);
      } catch (e) {
        console.warn('[editor] Failed to restore PM doc from JSON, falling back to markdown:', e);
        doc = markdownToPmDoc('', schemaWithLists);
      }
    } else {
      doc = markdownToPmDoc(rawValue || '', schemaWithLists);
    }

    // cmsBase may be "" in the shell (routes.py injects it empty for same-origin serving).
    // CollabConnection._wsUrl() needs an absolute URL to build ws://... so resolve here.
    const resolvedCmsBase = cmsBase || window.location.origin

    // Rich text fields use the collab WS path when docId is known
    if (fieldMeta.field_type === 'rich_text' && docId) {
      const clientID = Math.random().toString(36).slice(2) + Date.now().toString(36)
      const pmState = EditorState.create({
        doc,
        plugins: [...exampleSetup({ schema: schemaWithLists, menuBar: false }), collab({ version: 0, clientID })],
      })
      let collabConn = null
      const view = new EditorView(mountEl, {
        state: pmState,
        dispatchTransaction(tr) {
          const newState = view.state.apply(tr)
          view.updateState(newState)
          // Refresh toolbar active state on every transaction (selection moves too)
          const toolbar = document.getElementById(`pm-toolbar-${name}`)
          updateToolbarState(view, toolbar)
          if (collabConn && tr.docChanged) collabConn.onTransaction()
        },
      })
      collabConn = new CollabConnection({
        view,
        schema: schemaWithLists,
        documentId: docId,
        cmsBase: resolvedCmsBase,
        initialVersion: 0,
        toolbar: _makeCollabToolbarShim(),
        clientID,
        apiKey: apiKey || null,
      })
      state.pmInstances[name] = view
      state.collabConnections[name] = collabConn
    } else {
      // Standalone path for non-rich_text fields (markdown, etc.)
      const pmState = EditorState.create({
        doc,
        plugins: exampleSetup({ schema: schemaWithLists, menuBar: false }),
      });

      const view = new EditorView(mountEl, {
        state: pmState,
        dispatchTransaction(transaction) {
          const newState = view.state.apply(transaction);
          view.updateState(newState);
          // Refresh toolbar active state on every transaction (selection moves too)
          const toolbar = document.getElementById(`pm-toolbar-${name}`);
          updateToolbarState(view, toolbar);
          if (transaction.docChanged) {
            // Store as PM JSON when this field is a RichTextField (field_type === 'rich_text'),
            // otherwise serialise to markdown for backwards compatibility.
            const value = fieldMeta.field_type === 'rich_text'
              ? newState.doc.toJSON()
              : pmDocToMarkdown(newState.doc);
            onFieldChange(name, value);
          }
        },
      });

      state.pmInstances[name] = view;
    }

    // Wire up toolbar buttons (shared for both paths)
    const toolbar = document.getElementById(`pm-toolbar-${name}`);
    if (toolbar) {
      toolbar.addEventListener('mousedown', e => {
        e.preventDefault(); // prevent blur on editor
        const btn = e.target.closest('[data-cmd]');
        if (!btn) return;
        const cmd = btn.getAttribute('data-cmd');
        execPmCommand(state.pmInstances[name], schemaWithLists, cmd);
      });
    }
  }
}

/**
 * Destroy all active ProseMirror instances and collab connections, then clear both maps.
 */
export function destroyPmInstances() {
  for (const [, view] of Object.entries(state.pmInstances)) {
    try { view.destroy(); } catch { /* already destroyed */ }
  }
  for (const [, conn] of Object.entries(state.collabConnections)) {
    try { conn.destroy(); } catch { /* already destroyed */ }
  }
  state.pmInstances = {};
  state.collabConnections = {};
}
