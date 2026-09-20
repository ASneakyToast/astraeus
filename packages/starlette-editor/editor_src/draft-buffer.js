/**
 * draft-buffer.js — Crash survival for in-progress edits.
 *
 * Structured fields live only in `state.formData` until an explicit save, so a
 * reload or a backgrounded tab being evicted destroys them. This buffers them to
 * localStorage as they change.
 *
 * Not offline editing: a buffer covers the gap between editing and saving, on one
 * origin, for one browser. Rich text under an active collab connection streams to
 * the server over the WebSocket and is not buffered here.
 *
 * A buffer is written on change, and cleared on a successful save or a confirmed
 * discard. So one surviving at load time means the tab died mid-edit — which is
 * exactly when it is worth offering back.
 */

const PREFIX = 'astraeus:draft:';
const DEBOUNCE_MS = 500;

/** @type {ReturnType<typeof setTimeout>|null} */
let _timer = null;

/**
 * Storage key for a document being edited.
 *
 * New documents have no id yet, so they are keyed by type — one pending new
 * document per type, which matches what the shell can have open at once.
 *
 * @param {string|null} docId
 * @param {string} docType
 * @returns {string}
 */
export function draftKey(docId, docType) {
  return docId ? `${PREFIX}${docId}` : `${PREFIX}new:${docType}`;
}

/**
 * Buffer form data against a key, debounced so typing does not thrash storage.
 *
 * @param {string} key
 * @param {object} formData
 */
export function saveDraft(key, formData) {
  if (_timer) clearTimeout(_timer);
  _timer = setTimeout(() => writeDraft(key, formData), DEBOUNCE_MS);
}

/**
 * Write a buffer immediately, bypassing the debounce.
 *
 * On a full quota, drops the oldest buffer and retries once. Storage being
 * unavailable entirely (private mode, disabled) is not an error worth surfacing —
 * the buffer is a safety net, not the save path.
 *
 * @param {string} key
 * @param {object} formData
 */
export function writeDraft(key, formData) {
  const payload = JSON.stringify({ savedAt: new Date().toISOString(), formData });

  try {
    localStorage.setItem(key, payload);
  } catch {
    if (!evictOldestDraft()) return;
    try {
      localStorage.setItem(key, payload);
    } catch { /* still no room — give up quietly */ }
  }
}

/**
 * Read a buffer.
 *
 * @param {string} key
 * @returns {{savedAt: string, formData: object}|null}
 */
export function loadDraft(key) {
  let raw = null;
  try {
    raw = localStorage.getItem(key);
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed.formData !== 'object' || parsed.formData === null) {
      return null;
    }
    return parsed;
  } catch {
    // Corrupt entry — drop it so it stops being offered.
    clearDraft(key);
    return null;
  }
}

/**
 * Drop a buffer, and cancel any debounced write that would recreate it.
 *
 * @param {string} key
 */
export function clearDraft(key) {
  if (_timer) {
    clearTimeout(_timer);
    _timer = null;
  }

  try {
    localStorage.removeItem(key);
  } catch { /* nothing to do */ }
}

/**
 * Remove the least recently written buffer to make room.
 *
 * @returns {boolean} true if something was removed
 */
function evictOldestDraft() {
  let oldestKey = null;
  let oldestAt = null;

  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(PREFIX)) continue;

      let savedAt = '';
      try {
        savedAt = JSON.parse(localStorage.getItem(key) || '{}').savedAt || '';
      } catch { savedAt = ''; }

      if (oldestAt === null || savedAt < oldestAt) {
        oldestKey = key;
        oldestAt = savedAt;
      }
    }

    if (!oldestKey) return false;

    localStorage.removeItem(oldestKey);
    return true;
  } catch {
    // Storage unavailable entirely — nothing to evict.
    return false;
  }
}
