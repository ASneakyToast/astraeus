/**
 * prosemirror/toolbar.js — Toolbar command execution and active-state updates.
 */

import { toggleMark, setBlockType, wrapIn } from 'prosemirror-commands'
import { wrapInList, liftListItem } from 'prosemirror-schema-list'

/**
 * Build a toggle-list command: wraps into the list type if not currently in it,
 * or lifts out if already in a list.
 *
 * @param {import('prosemirror-model').NodeType} listType
 * @param {import('prosemirror-model').NodeType} itemType
 * @returns {function}
 */
function _toggleList(listType, itemType) {
  return (state, dispatch) => {
    const { $from, $to } = state.selection;
    for (let d = $from.depth; d >= 0; d--) {
      if ($from.node(d).type === listType) {
        return liftListItem(itemType)(state, dispatch);
      }
    }
    return wrapInList(listType)(state, dispatch);
  };
}

/**
 * Execute a named ProseMirror command from the toolbar.
 *
 * @param {import('prosemirror-view').EditorView} view
 * @param {import('prosemirror-model').Schema} schema
 * @param {string} cmd
 */
export function execPmCommand(view, schema, cmd) {
  const { state, dispatch } = view;
  const cmds = {
    toggleBold:    toggleMark(schema.marks.strong),
    toggleItalic:  toggleMark(schema.marks.em),
    toggleCode:    schema.marks.code ? toggleMark(schema.marks.code) : () => false,
    h1:            setBlockType(schema.nodes.heading, { level: 1 }),
    h2:            setBlockType(schema.nodes.heading, { level: 2 }),
    paragraph:     setBlockType(schema.nodes.paragraph),
    // Toggle list: wrap if not in a list, lift if already in one
    bulletList:    _toggleList(schema.nodes.bullet_list, schema.nodes.list_item),
    orderedList:   _toggleList(schema.nodes.ordered_list, schema.nodes.list_item),
    blockquote:    wrapIn(schema.nodes.blockquote),
  };
  const fn = cmds[cmd];
  if (fn) fn(state, dispatch);
  view.focus();
}

/**
 * Return true if the given mark type is active in the current selection.
 *
 * @param {import('prosemirror-state').EditorState} pmState
 * @param {string} markTypeName
 * @returns {boolean}
 */
export function hasMark(pmState, markTypeName) {
  const schema = pmState.schema;
  const markType = schema.marks[markTypeName];
  if (!markType) return false;
  const { from, $from, to, empty } = pmState.selection;
  if (empty) return !!markType.isInSet(pmState.storedMarks || $from.marks());
  return pmState.doc.rangeHasMark(from, to, markType);
}

/**
 * Return true if the cursor is inside a list node of the given type.
 *
 * @param {import('prosemirror-state').EditorState} pmState
 * @param {string} listTypeName
 * @returns {boolean}
 */
export function isInList(pmState, listTypeName) {
  const schema = pmState.schema;
  const listType = schema.nodes[listTypeName];
  if (!listType) return false;
  const { $from } = pmState.selection;
  for (let d = $from.depth; d >= 0; d--) {
    if ($from.node(d).type === listType) return true;
  }
  return false;
}

/**
 * Refresh toolbar button active states based on current ProseMirror selection.
 *
 * @param {import('prosemirror-view').EditorView} view
 * @param {HTMLElement|null} toolbar
 */
export function updateToolbarState(view, toolbar) {
  if (!toolbar) return;
  const { state: pmState } = view;
  const { $from } = pmState.selection;
  const parentType = $from.parent.type.name;
  const parentLevel = $from.parent.attrs?.level;

  toolbar.querySelectorAll('[data-cmd]').forEach(btn => {
    const cmd = btn.getAttribute('data-cmd');
    let active = false;
    switch (cmd) {
      case 'toggleBold':   active = hasMark(pmState, 'strong'); break;
      case 'toggleItalic': active = hasMark(pmState, 'em'); break;
      case 'toggleCode':   active = hasMark(pmState, 'code'); break;
      case 'h1':           active = parentType === 'heading' && parentLevel === 1; break;
      case 'h2':           active = parentType === 'heading' && parentLevel === 2; break;
      case 'blockquote':   active = parentType === 'blockquote'; break;
      case 'bulletList':   active = isInList(pmState, 'bullet_list'); break;
      case 'orderedList':  active = isInList(pmState, 'ordered_list'); break;
    }
    btn.classList.toggle('is-active', active);
  });
}
