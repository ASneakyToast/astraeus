/**
 * components/confirm.js — Modal confirmation dialog.
 */

import { el } from '../standard/utils.js'

/**
 * Show a confirmation dialog and return a Promise that resolves to the user's choice.
 *
 * @param {string} title
 * @param {string} body
 * @returns {Promise<boolean>}
 */
export function showConfirm(title, body) {
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
            class: 'btn btn--danger',
            onclick: () => { backdrop.remove(); resolve(true); }
          }, 'Delete')
        )
      )
    );
    document.body.appendChild(backdrop);
  });
}
