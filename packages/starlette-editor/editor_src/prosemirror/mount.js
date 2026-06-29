/**
 * prosemirror/mount.js — Mount and destroy ProseMirror editor instances.
 */

import { EditorState } from 'prosemirror-state'
import { EditorView } from 'prosemirror-view'
import { Schema } from 'prosemirror-model'
import { schema as basicSchema } from 'prosemirror-schema-basic'
import { addListNodes } from 'prosemirror-schema-list'
import { exampleSetup } from 'prosemirror-example-setup'

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
 * Mount ProseMirror on all .pm-editor placeholder elements in the form.
 *
 * @param {Array<{name: string, prop: object, meta: object}>} fields
 * @param {function} onFieldChange
 */
export async function mountProseMirrorEditors(fields, onFieldChange) {
  const pmFields = fields.filter(({ name, prop, meta }) => fieldWidget(name, prop, meta) === 'prosemirror');
  if (!pmFields.length) return;

  // Destroy any existing PM instances for this render cycle
  destroyPmInstances();

  for (const { name } of pmFields) {
    const mountEl = document.getElementById(`pm-mount-${name}`);
    if (!mountEl) continue;

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
          const fieldMeta = (state.schema?.[state.activeType]?.field_meta || {})[name] || {};
          const value = fieldMeta.field_type === 'rich_text'
            ? newState.doc.toJSON()
            : pmDocToMarkdown(newState.doc);
          onFieldChange(name, value);
        }
      },
    });

    state.pmInstances[name] = view;

    // Wire up toolbar buttons
    const toolbar = document.getElementById(`pm-toolbar-${name}`);
    if (toolbar) {
      toolbar.addEventListener('mousedown', e => {
        e.preventDefault(); // prevent blur on editor
        const btn = e.target.closest('[data-cmd]');
        if (!btn) return;
        const cmd = btn.getAttribute('data-cmd');
        execPmCommand(view, schemaWithLists, cmd);
      });
    }
  }
}

/**
 * Destroy all active ProseMirror instances and clear the instances map.
 */
export function destroyPmInstances() {
  for (const [, view] of Object.entries(state.pmInstances)) {
    try { view.destroy(); } catch { /* already destroyed */ }
  }
  state.pmInstances = {};
}
