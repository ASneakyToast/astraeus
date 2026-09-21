/**
 * components/pending-view.js — What is unpublished, and what to do about it.
 *
 * The small-screen landing (ADR 022 §1). A phone session is usually triage
 * rather than authoring: see what changed since the last publish, fix a typo,
 * approve something drafted on a desktop, publish. Browsing by type is still
 * there; it just is not the first thing asked of you.
 *
 * Reads the same endpoints as the changeset panel. It is a different question
 * asked of the same data — "what needs me?" rather than "how is this grouped?"
 * — so it renders its own view rather than reusing that layout.
 */

import { fetchDirtyDocs, fetchUnpublishedDocs, discardDraft } from '../api.js'
import { showConfirm } from './confirm.js'
import { showToast } from './toast.js'
import { el, docTitle, formatDate } from '../utils.js'

export class PendingView {
  /**
   * @param {object} opts
   * @param {(docType: string, docId: string) => void|Promise<void>} opts.onOpen
   *   Open a document for editing.
   * @param {() => void|Promise<void>} [opts.onPublish]
   *   Open the publish flow. Publishing is never done from here directly —
   *   it triggers a production rebuild and belongs behind the review step.
   */
  constructor({ onOpen, onPublish = null }) {
    this.onOpen = onOpen
    this.onPublish = onPublish
    this.el = null
    this.docs = []
    this.isLoading = false
  }

  /** @returns {HTMLElement} */
  mount() {
    this.el = el('div', { class: 'pending-view' })
    this.render()
    return this.el
  }

  /** Reload the outstanding documents and re-render. */
  async refresh() {
    this.isLoading = true
    this.render()

    try {
      const [dirty, unpublished] = await Promise.all([
        fetchDirtyDocs(),
        fetchUnpublishedDocs(),
      ])

      const seen = new Set()
      this.docs = []
      for (const doc of [...(dirty.documents ?? []), ...(unpublished.documents ?? [])]) {
        if (seen.has(doc.id)) continue
        seen.add(doc.id)
        this.docs.push(doc)
      }
    } catch (err) {
      this.docs = []
      showToast('error', 'Could not load pending changes', err.message)
    }

    this.isLoading = false
    this.render()
  }

  render() {
    if (!this.el) return
    this.el.innerHTML = ''

    if (this.isLoading) {
      this.el.appendChild(el('div', { class: 'pending-view__empty' },
        el('div', { class: 'loading-spinner', style: 'margin: 0 auto;' }),
      ))
      return
    }

    if (!this.docs.length) {
      // An empty screen is an invitation, not a dead end.
      this.el.appendChild(
        el('div', { class: 'pending-view__empty' },
          el('div', { class: 'pending-view__empty-title' }, 'Everything is published'),
          el('div', { class: 'pending-view__empty-body' },
            'Pick a type to start something new.'),
        ),
      )
      return
    }

    this.el.appendChild(
      el('div', { class: 'pending-view__header' },
        el('span', { class: 'pending-view__count' },
          `${this.docs.length} unpublished`),
        this.onPublish
          ? el('button', {
              class: 'btn btn--primary',
              type: 'button',
              onclick: () => this.onPublish(),
            }, 'Review & publish')
          : null,
      ),
    )

    for (const doc of this.docs) {
      this.el.appendChild(this._buildRow(doc))
    }
  }

  /**
   * @param {object} doc
   * @returns {HTMLElement}
   */
  _buildRow(doc) {
    const why = doc.draft_deleted
      ? 'Staged for deletion'
      : doc.published
        ? 'Edited since publishing'
        : 'Never published'

    return el('div', { class: 'pending-view__row' },
      el('button', {
        class: 'pending-view__open',
        type: 'button',
        onclick: () => this.onOpen(doc.doc_type, doc.id),
      },
        el('span', { class: 'pending-view__title' }, docTitle(doc)),
        el('span', { class: 'pending-view__meta' },
          `${why}${doc.updated_at ? ` · ${formatDate(doc.updated_at)}` : ''}`),
      ),
      el('button', {
        class: 'btn btn--ghost pending-view__discard',
        type: 'button',
        title: 'Discard draft',
        onclick: () => this._discard(doc),
      }, 'Discard'),
    )
  }

  /**
   * Throw away a document's unpublished edits.
   *
   * @param {object} doc
   */
  async _discard(doc) {
    const confirmed = await showConfirm(
      'Discard draft changes?',
      `"${docTitle(doc)}" reverts to the last published version. This cannot be undone.`,
      'Discard',
    )
    if (!confirmed) return

    try {
      await discardDraft(doc.id)
      showToast('success', 'Draft discarded', docTitle(doc))
      await this.refresh()
    } catch (err) {
      showToast('error', 'Could not discard draft', err.message)
    }
  }
}
