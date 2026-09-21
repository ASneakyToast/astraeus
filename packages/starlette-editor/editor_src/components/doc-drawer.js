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

/**
 * Both sidebars — below 640px they leave the layout flow and slide in together
 * as one navigation panel, so they open and close as a unit.
 *
 * @returns {HTMLElement[]}
 */
function panels() {
  return [...document.querySelectorAll('.sidebar-types, .sidebar-docs')];
}

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
  if (isDocDrawerOpen()) return;

  for (const el of panels()) el.classList.add(OPEN_CLASS);
  backdrop()?.classList.add(OPEN_CLASS);

  // Push a history entry so the device back gesture dismisses the drawer
  // instead of leaving the site, which is what back means to someone holding
  // a phone with a panel open over the content.
  try {
    history.pushState({ docDrawer: true }, '');
  } catch { /* history unavailable — the drawer still works */ }
}

/**
 * @param {boolean} [fromHistory] true when a popstate triggered this, so the
 *   history entry is already gone and must not be popped again.
 */
export function closeDocDrawer(fromHistory = false) {
  const wasOpen = isDocDrawerOpen();

  for (const el of panels()) el.classList.remove(OPEN_CLASS);
  backdrop()?.classList.remove(OPEN_CLASS);

  if (wasOpen && !fromHistory && history.state?.docDrawer) {
    try {
      history.back();
    } catch { /* history unavailable */ }
  }
}

export function toggleDocDrawer() {
  if (isDocDrawerOpen()) {
    closeDocDrawer();
  } else {
    openDocDrawer();
  }
}

/**
 * Close the drawer on Escape or on the device back gesture.
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

  const onPopState = () => {
    if (isDocDrawerOpen()) closeDocDrawer(true);
  };

  document.addEventListener('keydown', onKeydown);
  window.addEventListener('popstate', onPopState);

  return () => {
    document.removeEventListener('keydown', onKeydown);
    window.removeEventListener('popstate', onPopState);
  };
}
