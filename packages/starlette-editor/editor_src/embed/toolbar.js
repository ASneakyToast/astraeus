/**
 * EditToolbar — floating live-editing toolbar for the Astraeus embed script.
 *
 * States:
 *   viewing    — "✏️ Edit draft" button
 *   editing    — "✓ Saved" indicator + Discard + Publish
 *   saving     — "⏳ Saving..." indicator + Discard + Publish
 *   publishing — spinner
 *   published  — "✓ Published — rebuilding site"
 */
export class EditToolbar {
  constructor({ cmsBase, cmsElements }) {
    this.cmsBase = cmsBase
    this.cmsElements = cmsElements  // all [data-cms-id] elements on page
    this.state = 'viewing'          // 'viewing' | 'editing' | 'saving' | 'publishing' | 'published'
    this.activeElement = null       // currently-editing [data-cms-id] element
    this.el = null                  // the toolbar DOM element
  }

  mount() {
    this.el = document.createElement('div')
    this.el.id = 'astraeus-toolbar'
    this.el.style.cssText = `
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
      font-family: system-ui, sans-serif;
    `
    document.body.appendChild(this.el)
    this._render()
  }

  _render() {
    // Clear and re-render toolbar content based on this.state
    this.el.innerHTML = ''

    if (this.state === 'viewing') {
      const btn = this._makeButton('✏️ Edit draft', 'primary', () => this._startEditing())
      this.el.appendChild(btn)
    }

    if (this.state === 'editing' || this.state === 'saving') {
      const saveIndicator = this._makeIndicator(
        this.state === 'saving' ? '⏳ Saving...' : '✓ Saved'
      )
      const discardBtn = this._makeButton('Discard draft', 'ghost', () => this._discardDraft())
      const publishBtn = this._makeButton('Publish', 'success', () => this._publish())
      this.el.appendChild(saveIndicator)
      this.el.appendChild(discardBtn)
      this.el.appendChild(publishBtn)
    }

    if (this.state === 'publishing') {
      this.el.appendChild(this._makeIndicator('Publishing...'))
    }

    if (this.state === 'published') {
      this.el.appendChild(this._makeIndicator('✓ Published — rebuilding site'))
    }
  }

  _makeButton(label, variant, onClick) {
    const btn = document.createElement('button')
    btn.textContent = label
    const styles = {
      primary: 'background:#2563eb;color:#fff;border:none;',
      success: 'background:#16a34a;color:#fff;border:none;',
      ghost: 'background:rgba(255,255,255,0.1);color:#fff;border:1px solid rgba(255,255,255,0.2);',
    }
    btn.style.cssText = `
      padding: 10px 18px;
      border-radius: 8px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      backdrop-filter: blur(8px);
      ${styles[variant] || styles.primary}
    `
    btn.addEventListener('click', onClick)
    return btn
  }

  _makeIndicator(text) {
    const el = document.createElement('div')
    el.textContent = text
    el.style.cssText = `
      padding: 8px 14px;
      border-radius: 8px;
      background: rgba(0,0,0,0.7);
      color: #fff;
      font-size: 13px;
      backdrop-filter: blur(8px);
    `
    return el
  }

  setState(newState) {
    this.state = newState
    this._render()
  }

  async _startEditing() {
    // Import and activate edit mode for the first cms element
    // (multi-element selection is a future enhancement)
    const el = this.cmsElements[0]
    const { activateEditMode } = await import('./edit-mode.js')
    this.activeElement = el
    await activateEditMode(el, { cmsBase: this.cmsBase, toolbar: this })
    this.setState('editing')
  }

  async _discardDraft() {
    if (!this.activeElement) return
    const docId = this.activeElement.dataset.cmsId
    await fetch(`${this.cmsBase}/api/documents/${docId}/discard-draft`, {
      method: 'POST',
      credentials: 'include',
    })
    // Reload to get the published state
    window.location.reload()
  }

  async _publish() {
    if (!this.activeElement) return
    this.setState('publishing')
    const docId = this.activeElement.dataset.cmsId
    await fetch(`${this.cmsBase}/api/documents/${docId}/publish`, {
      method: 'POST',
      credentials: 'include',
    })
    this.setState('published')
  }
}
