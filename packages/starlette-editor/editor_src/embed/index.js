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

    // Boot the changeset panel alongside the toolbar
    const { ChangesetPanel } = await import('./changeset-panel.js')
    const changesetPanel = new ChangesetPanel({ cmsBase, toolbar })
    changesetPanel.mount()
    toolbar.changesetPanel = changesetPanel

    // Boot the AI chat panel (bottom-left, peer of the changeset panel)
    const { ChatPanel } = await import('./chat-panel.js')
    const apiKey = scriptEl?.dataset?.cmsApiKey ?? null
    const currentDocId = cmsElements[0]?.dataset?.cmsId ?? null

    // collab is lazily initialised by edit-mode.js; stubs for getDocContext until then
    let collab = null
    const chatPanel = new ChatPanel(cmsBase, null, {
      getDocContext: () => ({
        doc_id: currentDocId,
        version: collab?.currentVersion?.() ?? 0,
        draft_body: collab?.currentDoc?.() ?? null,
        selection: collab?.currentSelection?.() ?? null,
      }),
      apiKey,
    })
    chatPanel.mount()
    toolbar.setChatPanel(chatPanel)
  })()
}
