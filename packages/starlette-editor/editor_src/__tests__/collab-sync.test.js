/**
 * collab-sync.js — an editor takes the server's copy and version on connect.
 *
 * Uses real ProseMirror states (collab.test.js stubs the collab plugin out).
 */
import { describe, expect, it } from 'vitest'
import { EditorState } from 'prosemirror-state'
import { collab, getVersion, sendableSteps } from 'prosemirror-collab'
import { schemaWithLists as schema } from '../prosemirror/schema.js'
import { stateForServerCopy } from '../collab-sync.js'

const para = text => ({ type: 'doc', content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] })

function editorAt(docJSON, version = 0) {
  return EditorState.create({
    doc: schema.nodeFromJSON(docJSON),
    plugins: [collab({ version, clientID: 'me' })],
  })
}

function sync(state, docJSON, version) {
  return stateForServerCopy(state, { docJSON, version, clientID: 'me', schema })
}

describe('stateForServerCopy', () => {
  it('replaces a stale loaded copy with the server copy', () => {
    // The shell opened the published copy while the draft held your edits;
    // typing would have sent the stale copy back and overwritten the draft.
    const next = sync(editorAt(para('published')), para('draft'), 37)

    expect(next.doc.toJSON()).toEqual(para('draft'))
    expect(getVersion(next)).toBe(37)
    expect(next.plugins.filter(p => p.key.startsWith('collab$'))).toHaveLength(1)
  })

  it('takes the server version even when the copies already match', () => {
    // Editors counted from 0; against a server at 37 every step was rejected.
    const next = sync(editorAt(para('same')), para('same'), 37)

    expect(getVersion(next)).toBe(37)
    expect(next.doc.toJSON()).toEqual(para('same'))
  })

  it('leaves an editor that already matches alone', () => {
    expect(sync(editorAt(para('same'), 5), para('same'), 5)).toBeNull()
  })

  it('keeps unsent local edits', () => {
    let state = editorAt(para('base'))
    state = state.apply(state.tr.insertText('typed ', 1))
    expect(sendableSteps(state)).not.toBeNull()

    expect(sync(state, para('other'), 9)).toBeNull()
  })

  it('keeps the loaded copy but takes the version when the server copy will not parse', () => {
    const unparseable = { type: 'doc', content: [{ type: 'no_such_node' }] }
    const next = sync(editorAt(para('local')), unparseable, 4)

    expect(next.doc.toJSON()).toEqual(para('local'))
    expect(getVersion(next)).toBe(4)
  })

  it('keeps the loaded copy when the server has none yet', () => {
    expect(sync(editorAt(para('new post')), null, 0)).toBeNull()
  })
})
