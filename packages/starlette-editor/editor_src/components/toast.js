/**
 * components/toast.js — Toast notification system.
 */

import { el } from '../standard/utils.js'

/** @returns {HTMLElement} */
function getToastArea() {
  let area = document.querySelector('.toast-area');
  if (!area) {
    area = el('div', { class: 'toast-area' });
    document.body.appendChild(area);
  }
  return area;
}

const TOAST_ICONS = { success: '✓', error: '✗', info: 'ℹ', warning: '⚠' };

/**
 * Show a transient toast notification.
 *
 * @param {'success'|'error'|'info'|'warning'} type
 * @param {string} title
 * @param {string} [message]
 * @param {number} [duration=3500]
 */
export function showToast(type, title, message, duration = 3500) {
  const area = getToastArea();
  const toast = el('div', { class: `toast toast--${type}` },
    el('span', { class: 'toast__icon' }, TOAST_ICONS[type] || '•'),
    el('div', { class: 'toast__body' },
      el('div', { class: 'toast__title' }, title),
      message ? el('div', { class: 'toast__msg' }, message) : null
    )
  );
  area.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('is-leaving');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
  }, duration);
}
