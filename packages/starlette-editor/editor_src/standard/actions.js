/**
 * standard/actions.js — User-triggered async actions (select, save, publish, delete).
 */

import { state, setState } from '../state.js'
import {
  fetchDocuments,
  fetchDocument,
  createDocument,
  patchDocument,
  publishDocument,
  unpublishDocument,
  deleteDocument,
} from '../api.js'
import { showToast } from '../components/toast.js'
import { showConfirm } from '../components/confirm.js'
import { destroyPmInstances } from '../prosemirror/mount.js'
import { pmDocToMarkdown } from '../prosemirror/markdown.js'
import { docTitle } from './utils.js'

/**
 * Select a document type and load its document list.
 *
 * @param {string} typeKey
 */
export async function selectType(typeKey) {
  if (state.activeType === typeKey) return;

  destroyPmInstances();

  setState({
    activeType: typeKey,
    documents: [],
    docsTotal: 0,
    activeDocId: null,
    activeDoc: null,
    formData: {},
    isDirty: false,
    isLoadingDocs: true,
  });

  try {
    const result = await fetchDocuments(typeKey);
    setState({
      documents: result.documents || [],
      docsTotal: result.total || 0,
      isLoadingDocs: false,
    });
  } catch (err) {
    setState({ isLoadingDocs: false });
    showToast('error', 'Failed to load documents', err.message);
  }
}

/**
 * Select a document by ID and load its full body.
 *
 * @param {string} docId
 */
export async function selectDoc(docId) {
  if (state.activeDocId === docId) return;

  destroyPmInstances();

  setState({
    activeDocId: docId,
    activeDoc: null,
    formData: {},
    isDirty: false,
    isLoadingDoc: true,
  });

  try {
    const doc = await fetchDocument(docId);
    setState({
      activeDoc: doc,
      formData: { ...(doc.body || {}), __slug: doc.slug || '' },
      isLoadingDoc: false,
      isDirty: false,
    });
  } catch (err) {
    setState({ isLoadingDoc: false });
    showToast('error', 'Failed to load document', err.message);
  }
}

/**
 * Open the new document form (blank).
 */
export function openNewDoc() {
  if (!state.activeType) return;
  destroyPmInstances();
  setState({
    activeDocId: null,
    activeDoc: null,
    formData: { __slug: '' },
    isDirty: false,
  });
}

/**
 * Update a single field value in formData without triggering a full re-render.
 *
 * @param {string} name
 * @param {*} value
 */
export function onFieldChange(name, value) {
  state.formData = { ...state.formData, [name]: value };
  state.isDirty = true;
  // Only update the dirty indicator — no full re-render to preserve focus
  const dot = document.getElementById('dirty-dot');
  if (dot) dot.classList.add('is-visible');
}

/**
 * Save (create or update) the active document.
 */
export async function saveDocument() {
  if (!state.activeType) return;
  if (state.isSaving) return;

  setState({ isSaving: true });

  const { __slug, ...bodyFields } = state.formData;
  const slug = __slug || '';

  // Flush PM editor content to bodyFields before saving.
  // RichTextField fields store PM JSON; legacy markdown fields serialise to markdown.
  for (const [name, view] of Object.entries(state.pmInstances)) {
    const fieldMeta = (state.schema?.[state.activeType]?.field_meta || {})[name] || {};
    bodyFields[name] = fieldMeta.field_type === 'rich_text'
      ? view.state.doc.toJSON()
      : pmDocToMarkdown(view.state.doc);
  }

  try {
    let savedDoc;
    if (state.activeDocId) {
      savedDoc = await patchDocument(state.activeDocId, { body: bodyFields, slug });
    } else {
      savedDoc = await createDocument(state.activeType, bodyFields, slug);
    }

    const result = await fetchDocuments(state.activeType);

    setState({
      isSaving: false,
      activeDocId: savedDoc.id,
      activeDoc: savedDoc,
      formData: { ...(savedDoc.body || {}), __slug: savedDoc.slug || '' },
      isDirty: false,
      documents: result.documents || [],
      docsTotal: result.total || 0,
    });

    showToast('success', 'Saved', docTitle(savedDoc));
  } catch (err) {
    setState({ isSaving: false });
    showToast('error', 'Save failed', err.message);
  }
}

/**
 * Toggle publish state of the active document.
 */
export async function togglePublish() {
  const doc = state.activeDoc;
  if (!doc) return;

  try {
    let updated;
    if (doc.published) {
      updated = await unpublishDocument(doc.id);
      showToast('info', 'Unpublished', docTitle(doc));
    } else {
      updated = await publishDocument(doc.id);
      showToast('success', 'Published', docTitle(doc));
    }

    const result = await fetchDocuments(state.activeType);
    setState({
      activeDoc: updated,
      formData: { ...(updated.body || {}), __slug: updated.slug || '' },
      documents: result.documents || [],
      docsTotal: result.total || 0,
    });
  } catch (err) {
    showToast('error', 'Failed to change publish state', err.message);
  }
}

/**
 * Delete the active document after user confirmation.
 */
export async function deleteActiveDoc() {
  const doc = state.activeDoc;
  if (!doc) return;

  const confirmed = await showConfirm(
    'Delete document',
    `Are you sure you want to delete "${docTitle(doc)}"? This cannot be undone.`
  );
  if (!confirmed) return;

  try {
    await deleteDocument(doc.id);

    destroyPmInstances();

    const result = await fetchDocuments(state.activeType);
    setState({
      activeDocId: null,
      activeDoc: null,
      formData: {},
      isDirty: false,
      documents: result.documents || [],
      docsTotal: result.total || 0,
    });

    showToast('success', 'Deleted', docTitle(doc));
  } catch (err) {
    showToast('error', 'Delete failed', err.message);
  }
}
