/**
 * components/meta-panel.js — Document metadata details panel.
 */

import { el, formatDate } from '../standard/utils.js'
import { showToast } from './toast.js'

/**
 * Build the "Document info" collapsible panel for an existing document.
 *
 * @param {object} doc — document object from API
 * @returns {HTMLElement}
 */
export function buildMetaPanel(doc) {
  const panel = el('details', { class: 'doc-meta' });
  panel.appendChild(el('summary', { class: 'doc-meta__summary' }, 'Document info'));

  /** @param {string} key  @param {string|HTMLElement} valueNode */
  function metaRow(key, valueNode) {
    return el('div', { class: 'doc-meta__row' },
      el('span', { class: 'doc-meta__key' }, key),
      typeof valueNode === 'string'
        ? el('span', { class: 'doc-meta__val' }, valueNode)
        : valueNode
    );
  }

  // ID — monospace, copy on click
  const idVal = el('span', {
    class: 'doc-meta__val doc-meta__copy',
    title: 'Click to copy',
    onclick: () => {
      navigator.clipboard?.writeText(doc.id).then(() => showToast('info', 'Copied', doc.id));
    },
  }, doc.id || '—');
  panel.appendChild(metaRow('ID', idVal));

  if (doc.created_at)      panel.appendChild(metaRow('Created', formatDate(doc.created_at)));
  if (doc.updated_at)      panel.appendChild(metaRow('Updated', formatDate(doc.updated_at)));
  if (doc.published_at)    panel.appendChild(metaRow('Published at', formatDate(doc.published_at)));
  if (doc.import_ref)      panel.appendChild(metaRow('import_ref', doc.import_ref));
  if (doc.singleton_status) panel.appendChild(metaRow('Singleton', doc.singleton_status));

  return panel;
}
