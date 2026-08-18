/**
 * standard/actions.js — User-triggered async actions (select, save, publish, delete).
 */

import { state, setState } from '../state.js'
import {
  fetchDocuments,
  fetchDocument,
  createDocument,
  patchDocument,
  setDraftPublishState,
  setDraftDeleted,
  addDocToChangeset,
} from '../api.js'
import { setActiveChangesetId } from '../changeset-store.js'
import { showToast } from '../components/toast.js'
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
  // RichTextField fields with an active collab connection are already persisted via WS
  // steps — skip them here so stale in-memory state doesn't overwrite the server doc.
  for (const [name, view] of Object.entries(state.pmInstances)) {
    const fieldMeta = (state.schema?.[state.activeType]?.field_meta || {})[name] || {};
    if (fieldMeta.field_type === 'rich_text' && state.collabConnections[name]) continue
    bodyFields[name] = fieldMeta.field_type === 'rich_text'
      ? view.state.doc.toJSON()
      : pmDocToMarkdown(view.state.doc);
  }

  try {
    let savedDoc;
    if (state.activeDocId) {
      const { data, headers } = await patchDocument(
        state.activeDocId,
        { body: bodyFields, slug },
        { activeChangesetId: state.activeChangesetId || undefined },
      );
      savedDoc = data;

      // Server auto-created a changeset — adopt it
      const newCsId = headers.get('x-changeset-id');
      if (newCsId) {
        const csTitle = headers.get('x-changeset-title') || 'Untitled';
        setActiveChangesetId(newCsId);
        setState({
          activeChangesetId: newCsId,
          activeChangesetTitle: csTitle,
          activeChangesetDocCount: 1,
        }, false);
        showToast('info', `Created changeset '${csTitle}'`, 'Your edits are tracked');
      }
    } else {
      savedDoc = await createDocument(state.activeType, bodyFields, slug);

      // Auto-link new doc to active changeset
      if (state.activeChangesetId) {
        try {
          await addDocToChangeset(state.activeChangesetId, savedDoc.id);
          setState({ activeChangesetDocCount: (state.activeChangesetDocCount || 0) + 1 }, false);
        } catch (_err) {
          showToast('error', 'Could not link to changeset', _err.message);
        }
      }
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

  const intended = doc.draft_published ?? doc.published;
  const newIntended = !intended;
  const draftPublished = (newIntended !== doc.published) ? newIntended : null;

  try {
    const { data: updated, headers } = await setDraftPublishState(
      doc.id, draftPublished, state.activeChangesetId
    );

    const newCsId = headers.get('X-Changeset-Id');
    const newCsTitle = headers.get('X-Changeset-Title');
    if (newCsId) {
      setActiveChangesetId(newCsId);
      setState({ activeChangesetId: newCsId, activeChangesetTitle: newCsTitle });
    }

    const result = await fetchDocuments(state.activeType);
    setState({
      activeDoc: updated,
      formData: { ...(updated.body || {}), __slug: updated.slug || '' },
      documents: result.documents || [],
      docsTotal: result.total || 0,
    });

    if (draftPublished != null) {
      showToast('info', draftPublished ? 'Will publish with changeset' : 'Will unpublish with changeset', docTitle(doc));
    } else {
      showToast('info', 'Publish change cancelled', docTitle(doc));
    }
  } catch (err) {
    showToast('error', 'Failed to change publish state', err.message);
  }
}

/**
 * Toggle staged deletion of the active document.
 * First click stages the delete; second click cancels it.
 */
export async function deleteActiveDoc() {
  const doc = state.activeDoc;
  if (!doc) return;

  const willDelete = !doc.draft_deleted;

  try {
    const { data: updated, headers } = await setDraftDeleted(
      doc.id, willDelete ? true : null, state.activeChangesetId
    );

    const newCsId = headers.get('X-Changeset-Id');
    const newCsTitle = headers.get('X-Changeset-Title');
    if (newCsId) {
      setActiveChangesetId(newCsId);
      setState({ activeChangesetId: newCsId, activeChangesetTitle: newCsTitle });
    }

    const result = await fetchDocuments(state.activeType);
    setState({
      activeDoc: updated,
      formData: { ...(updated.body || {}), __slug: updated.slug || '' },
      documents: result.documents || [],
      docsTotal: result.total || 0,
    });

    if (willDelete) {
      showToast('info', 'Will delete with changeset', docTitle(doc));
    } else {
      showToast('info', 'Delete cancelled', docTitle(doc));
    }
  } catch (err) {
    showToast('error', 'Delete failed', err.message);
  }
}
