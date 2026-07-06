/**
 * ChangesetPanel — shows dirty documents and open changesets.
 * Allows grouping documents into a named changeset for atomic publish.
 *
 * Mounted alongside the EditToolbar; toggled via the "📋 Changesets" button.
 *
 * Usage::
 *   const panel = new ChangesetPanel({ cmsBase, toolbar })
 *   panel.mount()
 *   panel.toggle()
 */

const PANEL_STYLES = `
  position: fixed;
  bottom: 24px;
  right: 320px;
  z-index: 9998;
  width: 300px;
  background: #1e1e2e;
  color: #cdd6f4;
  border: 1px solid #313244;
  border-radius: 12px;
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 13px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.5);
  overflow: hidden;
`

const SECTION_HEADING_STYLES = `
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #89b4fa;
  padding: 8px 14px 4px;
  margin: 0;
`

const ITEM_STYLES = `
  padding: 6px 14px;
  border-bottom: 1px solid #181825;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
`

const BTN_BASE = `
  border: none;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  font-family: system-ui, -apple-system, sans-serif;
`

export class ChangesetPanel {
  /**
   * @param {{ cmsBase: string, toolbar: import('./toolbar.js').EditToolbar }} opts
   */
  constructor({ cmsBase, toolbar }) {
    this.cmsBase = cmsBase
    this.toolbar = toolbar
    /** @type {HTMLElement|null} */
    this.el = null
    this.visible = false
    /** @type {Array<{id: string, doc_type: string, slug: string, has_draft: boolean}>} */
    this.dirtyDocs = []
    /** @type {Array<{id: string, title: string, status: string, document_count: number}>} */
    this.openChangesets = []
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /** Append panel to document.body, initially hidden. */
  mount() {
    this.el = document.createElement('div')
    this.el.setAttribute('data-cms-changeset-panel', '')
    this.el.style.cssText = PANEL_STYLES
    this.el.style.display = 'none'
    document.body.appendChild(this.el)
  }

  /** Toggle panel visibility. Fetches fresh data when opening. */
  async toggle() {
    this.visible = !this.visible
    if (this.el) {
      this.el.style.display = this.visible ? 'block' : 'none'
    }
    if (this.visible) {
      await this.refresh()
    }
  }

  /**
   * Fetch dirty documents and open changesets in parallel, then re-render.
   * @returns {Promise<void>}
   */
  async refresh() {
    try {
      const [docsRes, csRes] = await Promise.all([
        fetch(`${this.cmsBase}/api/documents?has_draft=true`, { credentials: 'include' }),
        fetch(`${this.cmsBase}/api/changesets?status=open`, { credentials: 'include' }),
      ])
      this.dirtyDocs = (await docsRes.json()).documents ?? []
      this.openChangesets = (await csRes.json()).changesets ?? []
    } catch (_err) {
      this.dirtyDocs = []
      this.openChangesets = []
    }
    this._render()
  }

  // ── Private — rendering ────────────────────────────────────────────────────

  _render() {
    if (!this.el) return
    this.el.innerHTML = ''

    // Title bar
    const titleBar = document.createElement('div')
    titleBar.style.cssText = `
      padding: 12px 14px 10px;
      border-bottom: 1px solid #313244;
      display: flex;
      align-items: center;
      justify-content: space-between;
    `
    const title = document.createElement('span')
    title.style.cssText = 'font-weight: 700; color: #cdd6f4;'
    title.textContent = '📋 Changesets'

    const closeBtn = document.createElement('button')
    closeBtn.style.cssText = `${BTN_BASE} background: transparent; color: #6c7086; font-size: 16px; padding: 0 4px;`
    closeBtn.textContent = '×'
    closeBtn.addEventListener('click', () => this.toggle())

    titleBar.appendChild(title)
    titleBar.appendChild(closeBtn)
    this.el.appendChild(titleBar)

    // Section: Unpublished drafts
    const draftsHeading = document.createElement('p')
    draftsHeading.style.cssText = SECTION_HEADING_STYLES
    draftsHeading.textContent = `Unpublished drafts (${this.dirtyDocs.length})`
    this.el.appendChild(draftsHeading)

    if (this.dirtyDocs.length === 0) {
      const empty = document.createElement('div')
      empty.style.cssText = 'padding: 6px 14px 10px; color: #6c7086; font-size: 12px;'
      empty.textContent = 'No unpublished drafts'
      this.el.appendChild(empty)
    } else {
      this.dirtyDocs.forEach(doc => {
        const row = document.createElement('div')
        row.style.cssText = ITEM_STYLES

        const docLabel = document.createElement('span')
        docLabel.style.cssText = 'flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'
        docLabel.title = `${doc.doc_type}: ${doc.slug}`
        docLabel.textContent = `${doc.doc_type}: ${doc.slug}`

        const actionWrap = document.createElement('div')
        actionWrap.style.cssText = 'flex-shrink: 0;'

        if (this.openChangesets.length === 0) {
          const createBtn = document.createElement('button')
          createBtn.style.cssText = `${BTN_BASE} background: #313244; color: #cdd6f4;`
          createBtn.textContent = '+ New changeset'
          createBtn.addEventListener('click', () => this._promptAndCreate(doc.id))
          actionWrap.appendChild(createBtn)
        } else {
          const select = document.createElement('select')
          select.style.cssText = `
            background: #313244; color: #cdd6f4; border: 1px solid #45475a;
            border-radius: 6px; padding: 3px 6px; font-size: 12px; cursor: pointer;
          `

          const placeholder = document.createElement('option')
          placeholder.value = ''
          placeholder.textContent = '— Add to —'
          placeholder.disabled = true
          placeholder.selected = true
          select.appendChild(placeholder)

          this.openChangesets.forEach(cs => {
            const opt = document.createElement('option')
            opt.value = cs.id
            opt.textContent = `"${cs.title || 'Untitled'}" (${cs.document_count ?? 0} docs)`
            select.appendChild(opt)
          })

          const newOpt = document.createElement('option')
          newOpt.value = '__new__'
          newOpt.textContent = 'Create new…'
          select.appendChild(newOpt)

          select.addEventListener('change', async () => {
            const val = select.value
            if (!val) return
            if (val === '__new__') {
              await this._promptAndCreate(doc.id)
            } else {
              await this._addToChangeset(doc.id, val)
            }
          })

          actionWrap.appendChild(select)
        }

        row.appendChild(docLabel)
        row.appendChild(actionWrap)
        this.el.appendChild(row)
      })
    }

    // Section: Open changesets
    const csHeading = document.createElement('p')
    csHeading.style.cssText = SECTION_HEADING_STYLES
    csHeading.textContent = 'Open changesets'
    this.el.appendChild(csHeading)

    if (this.openChangesets.length === 0) {
      const empty = document.createElement('div')
      empty.style.cssText = 'padding: 6px 14px 10px; color: #6c7086; font-size: 12px;'
      empty.textContent = 'No open changesets'
      this.el.appendChild(empty)
    } else {
      this.openChangesets.forEach(cs => {
        const row = document.createElement('div')
        row.style.cssText = `${ITEM_STYLES} flex-wrap: wrap; gap: 6px;`

        const csLabel = document.createElement('span')
        csLabel.style.cssText = 'flex: 1 1 100%; color: #cdd6f4;'
        csLabel.textContent = `○ "${cs.title || 'Untitled'}" (${cs.document_count ?? 0} docs)`

        const btnRow = document.createElement('div')
        btnRow.style.cssText = 'display: flex; gap: 6px; flex-wrap: wrap;'

        const publishBtn = document.createElement('button')
        publishBtn.style.cssText = `${BTN_BASE} background: #a6e3a1; color: #1e1e2e;`
        publishBtn.textContent = 'Publish all'
        publishBtn.addEventListener('click', () => this._publishChangeset(cs.id))

        const scheduleBtn = document.createElement('button')
        scheduleBtn.style.cssText = `${BTN_BASE} background: #89b4fa; color: #1e1e2e;`
        scheduleBtn.textContent = 'Schedule'
        scheduleBtn.addEventListener('click', () => this._scheduleChangeset(cs.id, row))

        const deleteBtn = document.createElement('button')
        deleteBtn.style.cssText = `${BTN_BASE} background: #313244; color: #f38ba8;`
        deleteBtn.textContent = 'Delete'
        deleteBtn.addEventListener('click', () => this._deleteChangeset(cs.id))

        btnRow.appendChild(publishBtn)
        btnRow.appendChild(scheduleBtn)
        btnRow.appendChild(deleteBtn)

        row.appendChild(csLabel)
        row.appendChild(btnRow)
        this.el.appendChild(row)
      })
    }

    // Footer: New changeset
    const footer = document.createElement('div')
    footer.style.cssText = 'padding: 10px 14px; border-top: 1px solid #313244;'

    const newBtn = document.createElement('button')
    newBtn.style.cssText = `${BTN_BASE} background: #313244; color: #cdd6f4; width: 100%; text-align: left;`
    newBtn.textContent = '+ New changeset'
    newBtn.addEventListener('click', () => this._promptAndCreate(null))

    footer.appendChild(newBtn)
    this.el.appendChild(footer)
  }

  // ── Private — actions ──────────────────────────────────────────────────────

  /**
   * Prompt for a changeset title, create it, and optionally add a document.
   * @param {string|null} docId
   */
  async _promptAndCreate(docId) {
    const title = window.prompt('Changeset name (optional):') ?? ''
    await this._createAndAdd(docId, title)
  }

  /**
   * Add a document to an existing changeset, then refresh.
   * @param {string} docId
   * @param {string} changesetId
   */
  async _addToChangeset(docId, changesetId) {
    await fetch(`${this.cmsBase}/api/changesets/${changesetId}/documents/${docId}`, {
      method: 'POST',
      credentials: 'include',
    })
    await this.refresh()
  }

  /**
   * Create a new changeset, then add `docId` to it (if provided), then refresh.
   * @param {string|null} docId
   * @param {string} [title='']
   */
  async _createAndAdd(docId, title = '') {
    const res = await fetch(`${this.cmsBase}/api/changesets`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    })
    const cs = await res.json()
    if (docId) {
      await this._addToChangeset(docId, cs.id)
    } else {
      await this.refresh()
    }
  }

  /**
   * Atomically publish a changeset, then show a success toast.
   * @param {string} changesetId
   */
  async _publishChangeset(changesetId) {
    await fetch(`${this.cmsBase}/api/changesets/${changesetId}/publish`, {
      method: 'POST',
      credentials: 'include',
    })
    this._showToast('Published — site rebuilding')
    await this.refresh()
  }

  /**
   * Show an inline datetime picker and schedule the changeset.
   * @param {string} changesetId
   * @param {HTMLElement} rowEl - The changeset row element (for inline picker insertion).
   */
  async _scheduleChangeset(changesetId, rowEl) {
    // Remove any existing picker
    rowEl.querySelectorAll('[data-schedule-picker]').forEach(el => el.remove())

    const pickerWrap = document.createElement('div')
    pickerWrap.setAttribute('data-schedule-picker', '')
    pickerWrap.style.cssText = 'flex: 1 1 100%; display: flex; gap: 6px; align-items: center; padding-top: 4px;'

    const input = document.createElement('input')
    input.type = 'datetime-local'
    input.style.cssText = `
      background: #313244; color: #cdd6f4; border: 1px solid #45475a;
      border-radius: 6px; padding: 4px 8px; font-size: 12px; flex: 1;
    `

    const confirmBtn = document.createElement('button')
    confirmBtn.style.cssText = `${BTN_BASE} background: #89b4fa; color: #1e1e2e;`
    confirmBtn.textContent = 'Confirm'
    confirmBtn.addEventListener('click', async () => {
      if (!input.value) return
      const dt = new Date(input.value).toISOString()
      await fetch(`${this.cmsBase}/api/changesets/${changesetId}/schedule`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ publish_at: dt }),
      })
      await this.refresh()
    })

    pickerWrap.appendChild(input)
    pickerWrap.appendChild(confirmBtn)
    rowEl.appendChild(pickerWrap)
  }

  /**
   * Delete an open changeset after confirmation.
   * @param {string} changesetId
   */
  async _deleteChangeset(changesetId) {
    if (!confirm('Delete this changeset? Documents will not be affected.')) return
    await fetch(`${this.cmsBase}/api/changesets/${changesetId}`, {
      method: 'DELETE',
      credentials: 'include',
    })
    await this.refresh()
  }

  /**
   * Show a transient success toast for 2 seconds.
   * @param {string} message
   */
  _showToast(message) {
    const toast = document.createElement('div')
    toast.textContent = message
    toast.style.cssText = `
      position: fixed; bottom: 80px; right: 24px; z-index: 10000;
      background: #16a34a; color: #fff; padding: 10px 16px;
      border-radius: 8px; font-size: 14px; font-family: system-ui, sans-serif;
    `
    document.body.appendChild(toast)
    setTimeout(() => toast.remove(), 2000)
  }
}
