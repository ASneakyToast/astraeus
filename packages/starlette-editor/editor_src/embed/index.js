/**
 * Astraeus embed script — inline editing for static sites.
 *
 * Derive cmsBase from the script's own src attribute so no config is needed.
 * Checks authentication before doing anything visible.
 *
 * IMPORTANT: document.currentScript is only available during synchronous
 * script execution (not after any await). Capture it before the first await.
 */

// Capture synchronously before any await — document.currentScript is null after
const scriptEl = document.currentScript
const scriptUrl = scriptEl ? new URL(scriptEl.src) : null
const cmsBase = scriptUrl ? scriptUrl.origin : null

if (cmsBase) {
  ;(async () => {
    // Check authentication — exit silently if not logged in
    let authenticated = false
    try {
      const res = await fetch(`${cmsBase}/api/auth/me`, { credentials: 'include' })
      const data = await res.json()
      authenticated = data.authenticated === true
    } catch {
      return  // CMS unreachable — exit silently
    }
    if (!authenticated) return

    // Find all CMS-annotated elements on the page
    const cmsElements = Array.from(document.querySelectorAll('[data-cms-id]'))
    if (cmsElements.length === 0) return

    // Boot the toolbar
    const { EditToolbar } = await import('./toolbar.js')
    const toolbar = new EditToolbar({ cmsBase, cmsElements })
    toolbar.mount()
  })()
}
