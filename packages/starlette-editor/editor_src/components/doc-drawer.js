/**
 * components/doc-drawer.js — Navigation as a route stack on small screens.
 *
 * The document list is the only route to a document. Below 640px it used to be
 * `display: none`, which left an editor nothing could be loaded into; then a
 * 108px type rail beside a 282px document panel, which wrapped labels to three
 * lines and left the other half empty.
 *
 * Now one route at a time (ADR 022 §2): types, then documents, then back. The
 * state lives in two classes on <body> so the stylesheet owns the geometry —
 * every previous attempt put it in transforms that silently landed in the
 * wrong place.
 */

const OPEN = 'nav-open';
const DOCS = 'nav-docs';

/** @returns {boolean} */
export function isDocDrawerOpen() {
  return document.body.classList.contains(OPEN);
}

/** Open navigation at the route matching what is already selected. */
export function openDocDrawer(state = null) {
  if (isDocDrawerOpen()) return;

  document.body.classList.add(OPEN);
  document.body.classList.toggle(DOCS, Boolean(state?.activeType));
  backdrop()?.classList.add('is-open');

  // A history entry so the device back gesture dismisses navigation rather
  // than leaving the site, which is what back means with a panel open.
  try {
    history.pushState({ docDrawer: true }, '');
  } catch { /* history unavailable — navigation still works */ }
}

/**
 * @param {boolean} [fromHistory] true when a popstate triggered this, so the
 *   history entry is already gone and must not be popped again.
 */
export function closeDocDrawer(fromHistory = false) {
  const wasOpen = isDocDrawerOpen();

  document.body.classList.remove(OPEN, DOCS);
  backdrop()?.classList.remove('is-open');

  if (wasOpen && !fromHistory && history.state?.docDrawer) {
    try {
      history.back();
    } catch { /* history unavailable */ }
  }
}

/** Move to the document list — called when a type is chosen. */
export function showDocRoute() {
  document.body.classList.add(DOCS);
}

/** Back to the type list, without closing navigation. */
export function showTypeRoute() {
  document.body.classList.remove(DOCS);
}

export function toggleDocDrawer(state = null) {
  if (isDocDrawerOpen()) {
    closeDocDrawer();
  } else {
    openDocDrawer(state);
  }
}

/** @returns {HTMLElement|null} */
function backdrop() {
  return document.querySelector('.sidebar-docs__backdrop');
}

/**
 * Dismiss on Escape, and step back a route on the device back gesture.
 *
 * Returns an unsubscribe so a test can tear it down; the shell never does,
 * since navigation lives as long as the page.
 *
 * @returns {() => void}
 */
export function wireDocDrawerDismiss() {
  const onKeydown = e => {
    if (e.key !== 'Escape' || !isDocDrawerOpen()) return;

    // Escape steps back through the stack rather than closing it outright.
    if (document.body.classList.contains(DOCS)) {
      showTypeRoute();
    } else {
      closeDocDrawer();
    }
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
