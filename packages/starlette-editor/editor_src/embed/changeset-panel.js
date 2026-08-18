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

import {
  getActiveChangesetId,
  setActiveChangesetId,
  onActiveChangesetChange,
} from '../changeset-store.js'

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
    this.activeChangesetId = getActiveChangesetId()

    onActiveChangesetChange((newId) => {
      this.activeChangesetId = newId
      if (this.visible) this._render()
    })

    window.addEventListener('cms:chat-turn-done', () => this.refresh())
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
      const [dirtyRes, unpubRes, csRes] = await Promise.all([
        fetch(`${this.cmsBase}/api/documents?has_draft=true&exclude_types=chat_session,chat_message`, { credentials: 'include' }),
        fetch(`${this.cmsBase}/api/documents?published=false&exclude_types=chat_session,chat_message`, { credentials: 'include' }),
        fetch(`${this.cmsBase}/api/changesets?status=open`, { credentials: 'include' }),
      ])
      const dirtyDocs = (await dirtyRes.json()).documents ?? []
      const unpubDocs = (await unpubRes.json()).documents ?? []
      const seen = new Set()
      this.dirtyDocs = []
      for (const doc of dirtyDocs) {
        if (!seen.has(doc.id)) { seen.add(doc.id); this.dirtyDocs.push(doc); }
      }
      for (const doc of unpubDocs) {
        if (!seen.has(doc.id)) { seen.add(doc.id); this.dirtyDocs.push(doc); }
      }
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
        const isActive = cs.id === this.activeChangesetId
        const row = document.createElement('div')
        row.style.cssText = `${ITEM_STYLES} flex-wrap: wrap; gap: 6px;${isActive ? ' background: #181825;' : ''}`

        const csLabel = document.createElement('span')
        csLabel.style.cssText = `flex: 1 1 100%; color: ${isActive ? '#a6e3a1' : '#cdd6f4'};`
        csLabel.textContent = `${isActive ? '● ' : '○ '}"${cs.title || 'Untitled'}" (${cs.document_count ?? 0} docs)`

        const btnRow = document.createElement('div')
        btnRow.style.cssText = 'display: flex; gap: 6px; flex-wrap: wrap;'

        const activeBtn = document.createElement('button')
        if (isActive) {
          activeBtn.style.cssText = `${BTN_BASE} background: #a6e3a1; color: #1e1e2e; opacity: 0.7;`
          activeBtn.textContent = 'Active'
          activeBtn.disabled = true
        } else {
          activeBtn.style.cssText = `${BTN_BASE} background: #313244; color: #cdd6f4;`
          activeBtn.textContent = 'Set active'
          activeBtn.addEventListener('click', () => {
            setActiveChangesetId(cs.id)
            this.activeChangesetId = cs.id
            this._render()
          })
        }

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

        btnRow.appendChild(activeBtn)
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
    setActiveChangesetId(cs.id)
    this.activeChangesetId = cs.id
    if (docId) {
      await this._addToChangeset(docId, cs.id)
    } else {
      await this.refresh()
    }
  }

  /**
   * Fetch diff and show review modal before publishing.
   * @param {string} changesetId
   */
  async _publishChangeset(changesetId) {
    try {
      const res = await fetch(`${this.cmsBase}/api/changesets/${changesetId}/diff`, {
        credentials: 'include',
      })
      if (!res.ok) {
        this._showToast('Failed to load diff')
        return
      }
      const diffData = await res.json()
      this._showReviewModal(changesetId, diffData)
    } catch (_err) {
      this._showToast('Failed to load diff')
    }
  }

  /**
   * Show a modal with per-doc diffs and a confirm publish button.
   * @param {string} changesetId
   * @param {object} diffData
   */
  _showReviewModal(changesetId, diffData) {
    document.querySelectorAll('[data-publish-review-modal]').forEach(el => el.remove())

    const overlay = document.createElement('div')
    overlay.setAttribute('data-publish-review-modal', '')
    overlay.style.cssText = `
      position: fixed; inset: 0; z-index: 10000;
      background: rgba(0,0,0,0.6);
      display: flex; align-items: center; justify-content: center;
      font-family: system-ui, -apple-system, sans-serif;
    `

    const modal = document.createElement('div')
    modal.style.cssText = `
      background: #1e1e2e; color: #cdd6f4; border: 1px solid #313244;
      border-radius: 12px; width: 560px; max-height: 80vh; overflow-y: auto;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    `

    const header = document.createElement('div')
    header.style.cssText = 'padding: 16px 20px; border-bottom: 1px solid #313244; display: flex; align-items: center; justify-content: space-between;'
    const title = document.createElement('span')
    title.style.cssText = 'font-weight: 700; font-size: 15px;'
    title.textContent = 'Review & Publish'
    const closeBtn = document.createElement('button')
    closeBtn.style.cssText = `${BTN_BASE} background: transparent; color: #6c7086; font-size: 18px; padding: 0 4px;`
    closeBtn.textContent = '×'
    closeBtn.addEventListener('click', () => overlay.remove())
    header.appendChild(title)
    header.appendChild(closeBtn)
    modal.appendChild(header)

    const diffs = diffData.diffs || []
    if (diffs.length === 0) {
      const empty = document.createElement('div')
      empty.style.cssText = 'padding: 20px; color: #6c7086; text-align: center;'
      empty.textContent = 'No documents in this changeset.'
      modal.appendChild(empty)
    } else {
      diffs.forEach(d => {
        const row = document.createElement('div')
        row.style.cssText = 'padding: 10px 20px; border-bottom: 1px solid #181825;'

        const topLine = document.createElement('div')
        topLine.style.cssText = 'display: flex; align-items: center; justify-content: space-between; gap: 8px;'

        const label = document.createElement('span')
        label.style.cssText = 'flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'
        label.textContent = `${d.doc_type}: ${d.slug || '(no slug)'}`

        const badges = document.createElement('span')
        badges.style.cssText = 'flex-shrink: 0; display: flex; gap: 4px; font-size: 11px;'

        if (d.is_new) {
          const tag = document.createElement('span')
          tag.style.cssText = 'background: #a6e3a1; color: #1e1e2e; padding: 1px 6px; border-radius: 4px;'
          tag.textContent = 'NEW'
          badges.appendChild(tag)
        } else if (d.has_changes) {
          const tag = document.createElement('span')
          tag.style.cssText = 'background: #89b4fa; color: #1e1e2e; padding: 1px 6px; border-radius: 4px;'
          tag.textContent = `+${d.additions} -${d.deletions}`
          badges.appendChild(tag)
        } else {
          const tag = document.createElement('span')
          tag.style.cssText = 'background: #45475a; color: #cdd6f4; padding: 1px 6px; border-radius: 4px;'
          tag.textContent = 'No changes'
          badges.appendChild(tag)
        }

        topLine.appendChild(label)
        topLine.appendChild(badges)
        row.appendChild(topLine)

        if (d.also_in && d.also_in.length > 0) {
          const warn = document.createElement('div')
          warn.style.cssText = 'margin-top: 4px; color: #fab387; font-size: 11px;'
          const names = d.also_in.map(c => `"${c.title || 'Untitled'}"`).join(', ')
          warn.textContent = `⚠ Also in: ${names}`
          row.appendChild(warn)
        }

        if (d.has_changes && d.diff) {
          const toggle = document.createElement('button')
          toggle.style.cssText = `${BTN_BASE} background: transparent; color: #89b4fa; font-size: 11px; padding: 2px 0; margin-top: 4px;`
          toggle.textContent = 'Show diff ▸'
          const diffBlock = document.createElement('pre')
          diffBlock.style.cssText = `
            display: none; margin-top: 6px; padding: 8px; background: #11111b;
            border-radius: 6px; font-size: 11px; line-height: 1.4;
            overflow-x: auto; white-space: pre-wrap; color: #a6adc8;
          `
          diffBlock.textContent = d.diff

          toggle.addEventListener('click', () => {
            const show = diffBlock.style.display === 'none'
            diffBlock.style.display = show ? 'block' : 'none'
            toggle.textContent = show ? 'Hide diff ▾' : 'Show diff ▸'
          })

          row.appendChild(toggle)
          row.appendChild(diffBlock)
        }

        modal.appendChild(row)
      })
    }

    const footer = document.createElement('div')
    footer.style.cssText = 'padding: 14px 20px; border-top: 1px solid #313244; display: flex; justify-content: flex-end; gap: 8px;'

    const cancelBtn = document.createElement('button')
    cancelBtn.style.cssText = `${BTN_BASE} background: #313244; color: #cdd6f4;`
    cancelBtn.textContent = 'Cancel'
    cancelBtn.addEventListener('click', () => overlay.remove())

    const confirmBtn = document.createElement('button')
    confirmBtn.style.cssText = `${BTN_BASE} background: #a6e3a1; color: #1e1e2e; font-weight: 600;`
    confirmBtn.textContent = 'Confirm Publish'
    confirmBtn.addEventListener('click', async () => {
      confirmBtn.disabled = true
      confirmBtn.textContent = 'Publishing…'
      try {
        await fetch(`${this.cmsBase}/api/changesets/${changesetId}/publish`, {
          method: 'POST',
          credentials: 'include',
        })
        if (this.activeChangesetId === changesetId) {
          setActiveChangesetId(null)
          this.activeChangesetId = null
        }
        overlay.remove()
        this._showToast('Published — site rebuilding')
        await this.refresh()
      } catch (_err) {
        confirmBtn.disabled = false
        confirmBtn.textContent = 'Confirm Publish'
        this._showToast('Publish failed')
      }
    })

    footer.appendChild(cancelBtn)
    footer.appendChild(confirmBtn)
    modal.appendChild(footer)

    overlay.appendChild(modal)
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) overlay.remove()
    })
    document.body.appendChild(overlay)
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
    if (this.activeChangesetId === changesetId) {
      setActiveChangesetId(null)
      this.activeChangesetId = null
    }
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
