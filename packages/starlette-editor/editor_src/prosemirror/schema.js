/**
 * prosemirror/schema.js — The one ProseMirror schema.
 *
 * Both editing surfaces connect to the same collab authority, and
 * prosemirror-collab can only apply a step if both ends agree on the schema
 * a document is built from. Two independently-constructed schemas that happen
 * to match today are a silent correctness risk tomorrow: add a node type to
 * one and steps from that surface stop applying on the other, mid-session,
 * with no error that names the cause.
 *
 * So there is one, here, and both import it.
 */

import { Schema } from 'prosemirror-model'
import { schema as basicSchema } from 'prosemirror-schema-basic'
import { addListNodes } from 'prosemirror-schema-list'

/** Basic schema plus ordered and bullet lists. */
export const schemaWithLists = new Schema({
  nodes: addListNodes(basicSchema.spec.nodes, 'paragraph block*', 'block'),
  marks: basicSchema.spec.marks,
})

/**
 * Opaque per-connection identifier for collab step attribution.
 *
 * Only has to be unique among the clients on one document, which this is: it
 * combines randomness with the current time.
 *
 * @returns {string}
 */
export function generateClientID() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}
