/**
 * collab-sync.js — bring an editor in line with the server's copy on connect.
 */
import { EditorState } from 'prosemirror-state'
import { collab, getVersion, sendableSteps } from 'prosemirror-collab'

/**
 * The editor state matching the server's copy of a field, or null if the
 * editor already matches.
 *
 * On connect the server sends its copy of the field (the draft) and its
 * version. Editors used to keep whatever they had loaded and start counting
 * steps from 0. That broke two ways:
 *
 * - A stale copy (a tab left open, the shell showing the published copy) was
 *   sent back whole on the next keystroke and overwrote the draft.
 * - Once the server's version was past 0 — any save bumps it — every step was
 *   rejected for a version mismatch, silently, so body edits were lost while
 *   the toolbar said "Saved".
 *
 * Unsent local edits win: they are resent at their own version and the server
 * accepts or rejects them, so nothing typed is thrown away here.
 *
 * @param {EditorState} state   The editor's current state.
 * @param {object} server
 * @param {object|null} server.docJSON  The server's copy of the field, if any.
 * @param {number} server.version       The server's version for the field.
 * @param {string} server.clientID      This editor's collab client id.
 * @param {import('prosemirror-model').Schema} server.schema
 * @returns {EditorState|null}
 */
export function stateForServerCopy(state, { docJSON, version, clientID, schema }) {
  if (sendableSteps(state)) return null

  let doc = state.doc
  if (docJSON) {
    try {
      doc = schema.nodeFromJSON(docJSON)
    } catch {
      // A node this editor's schema can't represent — keep the loaded copy,
      // but still take the server's version so edits are accepted.
    }
  }

  if (doc.eq(state.doc) && getVersion(state) === version) return null

  // The collab plugin's version is fixed when it's created, so replace it.
  const plugins = state.plugins
    .filter(plugin => !plugin.key.startsWith('collab$'))
    .concat(collab({ version, clientID }))
  return EditorState.create({ doc, plugins })
}
