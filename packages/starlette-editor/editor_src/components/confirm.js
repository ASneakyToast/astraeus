/**
 * components/confirm.js — Modal confirmation dialog.
 */

import { el } from '../standard/utils.js'

/**
 * Show a confirmation dialog and return a Promise that resolves to the user's choice.
 *
 * @param {string} title
 * @param {string} body
 * @param {string} confirmLabel  Label for the confirming button.
 * @param {string} confirmVariant  Button modifier — 'danger' or 'primary'.
 * @returns {Promise<boolean>}
 */
export function showConfirm(title, body, confirmLabel = 'Delete', confirmVariant = 'danger') {
  return new Promise(resolve => {
    const backdrop = el('div', { class: 'overlay-backdrop' },
      el('div', { class: 'overlay-dialog' },
        el('div', { class: 'overlay-dialog__title' }, title),
        el('div', { class: 'overlay-dialog__body' }, body),
        el('div', { class: 'overlay-dialog__actions' },
          el('button', {
            class: 'btn btn--ghost',
            onclick: () => { backdrop.remove(); resolve(false); }
          }, 'Cancel'),
          el('button', {
            class: `btn btn--${confirmVariant}`,
            onclick: () => { backdrop.remove(); resolve(true); }
          }, confirmLabel)
        )
      )
    );
    document.body.appendChild(backdrop);
  });
}
