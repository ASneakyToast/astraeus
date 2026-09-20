/**
 * components/doc-drawer.js — Document list as a drawer on small screens.
 *
 * The document list is the only way to reach a document. Below 640px it used to
 * be `display: none`, which left the shell with an editor and no way to load
 * anything into it. Here it slides over the content instead, and the layout is
 * unchanged at wider widths where the list is a column.
 *
 * Interim: ED-5 replaces this with a real route stack (ADR 022).
 */

const OPEN_CLASS = 'is-open';

/** @returns {HTMLElement|null} */
function drawer() {
  return document.querySelector('.sidebar-docs');
}

/** @returns {HTMLElement|null} */
function backdrop() {
  return document.querySelector('.sidebar-docs__backdrop');
}

/** @returns {boolean} */
export function isDocDrawerOpen() {
  return drawer()?.classList.contains(OPEN_CLASS) ?? false;
}

export function openDocDrawer() {
  drawer()?.classList.add(OPEN_CLASS);
  backdrop()?.classList.add(OPEN_CLASS);
}

export function closeDocDrawer() {
  drawer()?.classList.remove(OPEN_CLASS);
  backdrop()?.classList.remove(OPEN_CLASS);
}

export function toggleDocDrawer() {
  if (isDocDrawerOpen()) {
    closeDocDrawer();
  } else {
    openDocDrawer();
  }
}

/**
 * Close the drawer on Escape.
 *
 * Returns an unsubscribe so a test can tear it down; the shell never does,
 * since the drawer lives as long as the page.
 *
 * @returns {() => void}
 */
export function wireDocDrawerDismiss() {
  const onKeydown = e => {
    if (e.key === 'Escape' && isDocDrawerOpen()) closeDocDrawer();
  };

  document.addEventListener('keydown', onKeydown);
  return () => document.removeEventListener('keydown', onKeydown);
}
