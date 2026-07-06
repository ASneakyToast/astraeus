/**
 * Activates inline edit mode for a [data-cms-id] element.
 * Fetches the draft body, replaces static content with live editable fields.
 */
export async function activateEditMode(element, { cmsBase, toolbar }) {
  const docId = element.dataset.cmsId

  // Fetch draft body
  const res = await fetch(`${cmsBase}/api/documents/${docId}?draft=true`, {
    credentials: 'include',
  })
  if (!res.ok) return
  const doc = await res.json()
  const body = doc.body || {}

  // Activate each annotated field within the element
  const fieldEls = element.querySelectorAll('[data-cms-field]')
  for (const fieldEl of fieldEls) {
    const fieldName = fieldEl.dataset.cmsField
    const fieldValue = body[fieldName]
    if (fieldValue === undefined) continue

    await activateField(fieldEl, {
      fieldName,
      fieldValue,
      docId,
      cmsBase,
      toolbar,
    })
  }

  // Add visual affordance to the container
  element.style.outline = '2px dashed rgba(37, 99, 235, 0.4)'
  element.style.outlineOffset = '4px'
}

export async function activateField(el, { fieldName, fieldValue, docId, cmsBase, toolbar }) {
  const tag = el.tagName.toLowerCase()

  // Rich text fields — detected by fieldValue being a ProseMirror JSON doc
  if (typeof fieldValue === 'object' && fieldValue !== null && fieldValue.type === 'doc') {
    // Mount ProseMirror — Phase 3B will wire up the WS collab here
    // For Phase 3A: mount a basic non-collab ProseMirror editor
    const { mountProseMirrorOnElement } = await import('./prosemirror-embed.js')
    await mountProseMirrorOnElement(el, { doc: fieldValue, docId, fieldName, cmsBase, toolbar })
    return
  }

  // Simple text fields (h1–h6, p, span)
  if (typeof fieldValue === 'string' && ['h1','h2','h3','h4','h5','h6','p','span'].includes(tag)) {
    el.contentEditable = 'true'
    el.style.outline = '1px dashed rgba(37, 99, 235, 0.5)'
    el.style.minHeight = '1em'

    // Debounced PATCH on input
    let debounceTimer
    el.addEventListener('input', () => {
      clearTimeout(debounceTimer)
      toolbar.setState('saving')
      debounceTimer = setTimeout(async () => {
        await fetch(`${cmsBase}/api/documents/${docId}`, {
          method: 'PATCH',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ body: { [fieldName]: el.textContent } }),
        })
        toolbar.setState('editing')
      }, 800)
    })
    return
  }
}
