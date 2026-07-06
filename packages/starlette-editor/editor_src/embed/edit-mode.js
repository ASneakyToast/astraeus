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

  // ── 1. Rich text fields (ProseMirror JSON doc) ──────────────────────────────
  if (typeof fieldValue === 'object' && fieldValue !== null && fieldValue.type === 'doc') {
    const { mountProseMirrorOnElement } = await import('./prosemirror-embed.js')
    await mountProseMirrorOnElement(el, { doc: fieldValue, docId, fieldName, cmsBase, toolbar })
    return
  }

  // ── 2. Markdown textarea modal ───────────────────────────────────────────────
  // Triggered when value is a plain string AND element has data-cms-field-type="markdown" OR is a <div>
  if (typeof fieldValue === 'string' && (el.dataset.cmsFieldType === 'markdown' || tag === 'div')) {
    _addEditAffordance(el)
    el.addEventListener('click', (e) => {
      e.stopPropagation()
      _openMarkdownModal(fieldValue, async (newValue) => {
        fieldValue = newValue
        toolbar.setState('saving')
        await patchField(cmsBase, docId, fieldName, newValue)
        toolbar.setState('editing')
      })
    })
    return
  }

  // ── 3. Simple text fields (h1–h6, p, span) ──────────────────────────────────
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
        await patchField(cmsBase, docId, fieldName, el.textContent)
        toolbar.setState('editing')
      }, 800)
    })
    return
  }

  // ── 4. Tags array editor ─────────────────────────────────────────────────────
  if (Array.isArray(fieldValue)) {
    _addEditAffordance(el)
    el.addEventListener('click', (e) => {
      e.stopPropagation()
      _openTagsEditor(el, fieldValue, async (newTags) => {
        fieldValue = newTags
        toolbar.setState('saving')
        await patchField(cmsBase, docId, fieldName, newTags)
        toolbar.setState('editing')
      })
    })
    return
  }

  // ── 5. Image picker ──────────────────────────────────────────────────────────
  if (fieldValue && typeof fieldValue === 'object' && 'src' in fieldValue) {
    _addEditAffordance(el)
    const CONFIG = window.__EDITOR_CONFIG__ || {}
    el.addEventListener('click', (e) => {
      e.stopPropagation()
      _openImageEditor(el, fieldValue, CONFIG, async (newValue) => {
        fieldValue = newValue
        toolbar.setState('saving')
        await patchField(cmsBase, docId, fieldName, newValue)
        // Update the live <img> in the element without a reload
        const img = el.querySelector('img')
        if (img && newValue.src) {
          img.src = newValue.src
          img.alt = newValue.alt || ''
        }
        toolbar.setState('editing')
      })
    })
    return
  }
}

// ────────────────────────────────────────────────────────────────────────────
// PATCH helper
// ────────────────────────────────────────────────────────────────────────────

async function patchField(cmsBase, docId, fieldName, value) {
  await fetch(`${cmsBase}/api/documents/${docId}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ body: { [fieldName]: value } }),
  })
}

// ────────────────────────────────────────────────────────────────────────────
// Shared affordance helper
// ────────────────────────────────────────────────────────────────────────────

function _addEditAffordance(el) {
  el.style.outline = '1px dashed rgba(37, 99, 235, 0.5)'
  el.style.cursor = 'pointer'
  el.title = 'Click to edit'
}

// ────────────────────────────────────────────────────────────────────────────
// Markdown modal
// ────────────────────────────────────────────────────────────────────────────

function _openMarkdownModal(currentValue, onSave) {
  const overlay = document.createElement('div')
  Object.assign(overlay.style, {
    position: 'fixed', inset: '0', zIndex: '99999',
    background: 'rgba(0,0,0,0.75)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    padding: '24px',
  })

  const panel = document.createElement('div')
  Object.assign(panel.style, {
    background: '#fff', borderRadius: '8px',
    width: '100%', maxWidth: '800px',
    display: 'flex', flexDirection: 'column',
    gap: '12px', padding: '24px',
    boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
    maxHeight: '90vh',
  })

  const label = document.createElement('p')
  label.textContent = 'Edit body markdown (Cmd/Ctrl+Enter to save, Esc to cancel)'
  Object.assign(label.style, { margin: '0', fontSize: '13px', color: '#555' })

  const textarea = document.createElement('textarea')
  textarea.value = currentValue
  Object.assign(textarea.style, {
    width: '100%', flex: '1', minHeight: '400px',
    fontFamily: 'monospace', fontSize: '14px', lineHeight: '1.6',
    padding: '12px', border: '1px solid #ccc', borderRadius: '4px',
    resize: 'vertical', boxSizing: 'border-box',
    color: '#1a1a1a', background: '#fafafa',
  })

  const btnRow = document.createElement('div')
  Object.assign(btnRow.style, { display: 'flex', gap: '8px', justifyContent: 'flex-end' })

  const cancelBtn = _makeBtn('Cancel', '#6b7280', () => overlay.remove())
  const saveBtn = _makeBtn('Save', '#2563eb', async () => {
    overlay.remove()
    await onSave(textarea.value)
  })

  btnRow.appendChild(cancelBtn)
  btnRow.appendChild(saveBtn)
  panel.appendChild(label)
  panel.appendChild(textarea)
  panel.appendChild(btnRow)
  overlay.appendChild(panel)
  document.body.appendChild(overlay)
  textarea.focus()

  // Keyboard shortcuts
  textarea.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { overlay.remove() }
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      overlay.remove()
      onSave(textarea.value)
    }
  })

  // Click outside panel to cancel
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) overlay.remove()
  })
}

// ────────────────────────────────────────────────────────────────────────────
// Tags editor (floating panel)
// ────────────────────────────────────────────────────────────────────────────

function _openTagsEditor(anchorEl, currentTags, onSave) {
  // Close any existing tags panel
  document.querySelector('.__cms-tags-panel')?.remove()

  const tags = [...currentTags]
  const rect = anchorEl.getBoundingClientRect()

  const panel = document.createElement('div')
  panel.className = '__cms-tags-panel'
  Object.assign(panel.style, {
    position: 'fixed',
    top: `${rect.bottom + window.scrollY + 6}px`,
    left: `${rect.left + window.scrollX}px`,
    zIndex: '99999',
    background: '#fff',
    border: '1px solid #d1d5db',
    borderRadius: '8px',
    padding: '12px',
    boxShadow: '0 8px 30px rgba(0,0,0,0.15)',
    minWidth: '280px',
    maxWidth: '420px',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  })

  function render() {
    panel.innerHTML = ''

    const chipsRow = document.createElement('div')
    Object.assign(chipsRow.style, { display: 'flex', flexWrap: 'wrap', gap: '6px' })

    tags.forEach((tag, i) => {
      const chip = document.createElement('span')
      chip.style.cssText = 'display:inline-flex;align-items:center;gap:4px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:999px;padding:2px 10px;font-size:13px;color:#1d4ed8;'
      chip.textContent = `#${tag}`

      const removeBtn = document.createElement('button')
      removeBtn.textContent = '✕'
      removeBtn.style.cssText = 'background:none;border:none;cursor:pointer;font-size:11px;color:#6b7280;padding:0;line-height:1;'
      removeBtn.addEventListener('click', () => {
        tags.splice(i, 1)
        render()
      })
      chip.appendChild(removeBtn)
      chipsRow.appendChild(chip)
    })
    panel.appendChild(chipsRow)

    const inputRow = document.createElement('div')
    Object.assign(inputRow.style, { display: 'flex', gap: '6px' })

    const input = document.createElement('input')
    input.type = 'text'
    input.placeholder = 'Add tag…'
    input.style.cssText = 'flex:1;padding:4px 8px;border:1px solid #d1d5db;border-radius:4px;font-size:13px;outline:none;'

    const addBtn = _makeBtn('Add', '#2563eb', () => {
      const val = input.value.trim().replace(/^#+/, '')
      if (val && !tags.includes(val)) { tags.push(val); render() }
      else input.focus()
    })
    addBtn.style.padding = '4px 10px'
    addBtn.style.fontSize = '13px'

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { addBtn.click(); e.preventDefault() }
      if (e.key === 'Escape') { panel.remove() }
    })

    inputRow.appendChild(input)
    inputRow.appendChild(addBtn)
    panel.appendChild(inputRow)

    const btnRow = document.createElement('div')
    Object.assign(btnRow.style, { display: 'flex', gap: '6px', justifyContent: 'flex-end', borderTop: '1px solid #f3f4f6', paddingTop: '8px' })

    const cancelBtn = _makeBtn('Cancel', '#6b7280', () => panel.remove())
    cancelBtn.style.padding = '4px 10px'
    cancelBtn.style.fontSize = '13px'

    const saveBtn = _makeBtn('Save', '#2563eb', async () => {
      panel.remove()
      await onSave([...tags])
    })
    saveBtn.style.padding = '4px 10px'
    saveBtn.style.fontSize = '13px'

    btnRow.appendChild(cancelBtn)
    btnRow.appendChild(saveBtn)
    panel.appendChild(btnRow)

    input.focus()
  }

  render()
  document.body.appendChild(panel)

  // Click outside closes and discards
  function onOutsideClick(e) {
    if (!panel.contains(e.target) && e.target !== anchorEl) {
      panel.remove()
      document.removeEventListener('click', onOutsideClick, true)
    }
  }
  // Defer listener so the opening click doesn't immediately close it
  setTimeout(() => document.addEventListener('click', onOutsideClick, true), 0)
}

// ────────────────────────────────────────────────────────────────────────────
// Image editor
// ────────────────────────────────────────────────────────────────────────────

function _openImageEditor(anchorEl, currentValue, CONFIG, onSave) {
  if (CONFIG.mediaBase) {
    // Use mediakit iframe picker
    const overlay = document.createElement('div')
    Object.assign(overlay.style, {
      position: 'fixed', inset: '0', zIndex: '99999',
      background: 'rgba(0,0,0,0.75)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    })

    const closeOverlay = () => {
      overlay.remove()
      window.removeEventListener('message', onMessage)
    }

    const closeBtn = document.createElement('button')
    closeBtn.textContent = '✕'
    closeBtn.style.cssText = 'position:absolute;top:16px;right:16px;background:#fff;border:none;cursor:pointer;font-size:20px;width:36px;height:36px;border-radius:50%;z-index:1;'
    closeBtn.addEventListener('click', closeOverlay)

    const iframe = document.createElement('iframe')
    iframe.src = `${CONFIG.mediaBase}/admin?picker=1`
    Object.assign(iframe.style, { width: '90vw', height: '85vh', border: 'none', borderRadius: '8px' })

    overlay.appendChild(closeBtn)
    overlay.appendChild(iframe)
    document.body.appendChild(overlay)

    overlay.addEventListener('click', (e) => { if (e.target === overlay) closeOverlay() })

    function onMessage(event) {
      const data = event.data
      if (!data) return
      const type = typeof data === 'string' ? data : data.type
      if (type === 'mediakit:asset-selected') {
        const asset = typeof data === 'object' ? data : {}
        closeOverlay()
        onSave({ src: asset.url || asset.key || '', alt: asset.alt_text || '' })
      } else if (type === 'mediakit:picker-cancelled') {
        closeOverlay()
      }
    }
    window.addEventListener('message', onMessage)
  } else {
    // Fallback: small URL + alt form modal
    const overlay = document.createElement('div')
    Object.assign(overlay.style, {
      position: 'fixed', inset: '0', zIndex: '99999',
      background: 'rgba(0,0,0,0.75)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '24px',
    })

    const panel = document.createElement('div')
    Object.assign(panel.style, {
      background: '#fff', borderRadius: '8px',
      width: '100%', maxWidth: '480px',
      padding: '24px', display: 'flex', flexDirection: 'column', gap: '12px',
      boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
    })

    const title = document.createElement('p')
    title.textContent = 'Update hero image'
    Object.assign(title.style, { margin: '0', fontWeight: '600', fontSize: '15px' })

    const srcInput = _makeTextInput('Image URL', currentValue.src || '')
    const altInput = _makeTextInput('Alt text', currentValue.alt || '')

    const btnRow = document.createElement('div')
    Object.assign(btnRow.style, { display: 'flex', gap: '8px', justifyContent: 'flex-end' })

    const cancelBtn = _makeBtn('Cancel', '#6b7280', () => overlay.remove())
    const saveBtn = _makeBtn('Save', '#2563eb', async () => {
      overlay.remove()
      await onSave({ src: srcInput.value.trim(), alt: altInput.value.trim() })
    })

    btnRow.appendChild(cancelBtn)
    btnRow.appendChild(saveBtn)

    panel.appendChild(title)
    panel.appendChild(srcInput)
    panel.appendChild(altInput)
    panel.appendChild(btnRow)
    overlay.appendChild(panel)
    document.body.appendChild(overlay)
    srcInput.focus()

    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove() })
    panel.addEventListener('keydown', (e) => { if (e.key === 'Escape') overlay.remove() })
  }
}

// ────────────────────────────────────────────────────────────────────────────
// Small DOM helpers
// ────────────────────────────────────────────────────────────────────────────

function _makeBtn(text, bgColor, onClick) {
  const btn = document.createElement('button')
  btn.textContent = text
  btn.style.cssText = `background:${bgColor};color:#fff;border:none;border-radius:4px;padding:8px 16px;font-size:14px;cursor:pointer;font-weight:500;`
  btn.addEventListener('click', onClick)
  return btn
}

function _makeTextInput(placeholder, value) {
  const input = document.createElement('input')
  input.type = 'text'
  input.placeholder = placeholder
  input.value = value
  input.style.cssText = 'width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:4px;font-size:14px;box-sizing:border-box;outline:none;'
  return input
}
