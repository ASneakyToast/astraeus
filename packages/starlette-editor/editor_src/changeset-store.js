/**
 * changeset-store.js — Shared active-changeset state via localStorage.
 *
 * All three editing surfaces (shell, embed, chat) read/write through this
 * module so they stay in sync on the same origin.
 */

const KEY = 'astraeus:activeChangesetId';

/** @returns {string|null} */
export function getActiveChangesetId() {
  return localStorage.getItem(KEY) ?? null;
}

/**
 * Set (or clear) the active changeset. Fires a synthetic StorageEvent so
 * same-page listeners are notified (native storage events only fire cross-page).
 *
 * @param {string|null} id
 */
export function setActiveChangesetId(id) {
  const prev = localStorage.getItem(KEY);
  if (id == null) {
    localStorage.removeItem(KEY);
  } else {
    localStorage.setItem(KEY, id);
  }
  window.dispatchEvent(
    new StorageEvent('storage', { key: KEY, oldValue: prev, newValue: id ?? null }),
  );
}

/**
 * Subscribe to active-changeset changes (from any surface on this origin).
 *
 * @param {(id: string|null) => void} callback
 * @returns {() => void} unsubscribe
 */
export function onActiveChangesetChange(callback) {
  const handler = (e) => {
    if (e.key === KEY) callback(e.newValue ?? null);
  };
  window.addEventListener('storage', handler);
  return () => window.removeEventListener('storage', handler);
}
