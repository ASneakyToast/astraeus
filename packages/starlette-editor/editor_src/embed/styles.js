/**
 * Styles for the embed's own chrome on a host site.
 *
 * The changeset panel, chat panel, publish drawer and toasts are written
 * against the shared design tokens (var(--bg-elevated) …) and, for the drawer
 * and toasts, class names styled by editor.css. The shell loads both. The host
 * site loads neither, and must not: tokens.css defines :root variables and
 * editor.css styles `.btn`, which collide with the host's own. With nothing
 * defining them every var() resolved to nothing, so the panels drew with no
 * background and no border.
 *
 * So the embed supplies what its chrome needs, scoped to its own elements:
 * the tokens as custom properties on those elements (they cascade to children
 * and touch nothing else), and the drawer/toast rules under selectors only
 * the editor's elements match. Nothing here reaches the host's markup.
 *
 * The values are tokens.css's dark ramp. A test keeps them equal.
 */

/** The editor's elements. Anything inside one of these gets the tokens. */
export const CHROME_SELECTORS = [
  '[data-cms-changeset-panel]',
  '[data-cms-chat-panel]',
  '#changeset-drawer',
  '.toast-area',
]

/** tokens.css `:root` values the embed's chrome uses. Kept equal by embed-styles.test.js. */
export const CHROME_TOKENS = {
  '--bg-base': '#0d0d0d',
  '--bg-elevated': '#1a1a1a',
  '--bg-hover': '#202020',
  '--border-subtle': '#474747',
  '--border-default': '#5f5f5f',
  '--border-strong': '#7a7a7a',
  '--text-primary': '#f0f0f0',
  '--text-secondary': '#a3a3a3',
  '--text-muted': '#7c7c7c',
  '--accent': '#e8e8e8',
  '--accent-on': '#0d0d0d',
  '--accent-hover': '#ffffff',
  '--pending': '#e04b45',
  '--pending-dim': 'rgba(224, 75, 69, 0.15)',
  '--red': 'var(--pending)',
  '--red-dim': 'var(--pending-dim)',
  '--green': '#2ea043',
  '--yellow': '#d29922',
  '--space-1': '4px',
  '--space-2': '8px',
  '--space-3': '12px',
  '--space-4': '16px',
  '--space-5': '20px',
  '--radius-sm': '4px',
  '--radius-md': '6px',
  '--radius-lg': '8px',
  '--font-size-xs': '11px',
  '--font-size-sm': '12px',
  '--font-size-md': '14px',
  '--font-sans': '-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", system-ui, sans-serif',
  '--font-mono': '"JetBrains Mono", "Fira Code", "SF Mono", ui-monospace, monospace',
  '--target-min': '44px',
  '--transition-fast': '100ms ease',
}

const tokenBlock = Object.entries(CHROME_TOKENS)
  .map(([name, value]) => `  ${name}: ${value};`)
  .join('\n')

// Rules below are editor.css's, copied for the pieces the embed shows, with
// every selector prefixed so they only match the editor's own elements and
// the keyframes renamed so they cannot replace the host's.
const CHROME_CSS = `
${CHROME_SELECTORS.join(',\n')} {
${tokenBlock}
}

/* Buttons inside the publish drawer */
#changeset-drawer .btn {
  display: inline-flex; align-items: center; justify-content: center;
  gap: var(--space-1); min-height: var(--target-min);
  padding: 5px var(--space-3); border-radius: var(--radius-sm);
  font-family: var(--font-sans); font-size: var(--font-size-sm); font-weight: 500;
  line-height: 1.4; cursor: pointer; border: 1px solid transparent;
  transition: all var(--transition-fast); text-decoration: none; white-space: nowrap;
}
#changeset-drawer .btn:disabled { opacity: 0.4; cursor: not-allowed; }
#changeset-drawer .btn--primary { background: var(--accent); color: var(--accent-on); border-color: var(--accent); }
#changeset-drawer .btn--primary:hover:not(:disabled) { background: var(--accent-hover); border-color: var(--accent-hover); }
#changeset-drawer .btn--ghost { background: transparent; color: var(--text-secondary); border-color: var(--border-default); }
#changeset-drawer .btn--ghost:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-primary); border-color: var(--border-strong); }

/* Publish drawer */
#changeset-drawer.changeset-overlay {
  position: fixed; inset: 0; z-index: 2147483100;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0, 0, 0, 0.6); backdrop-filter: blur(2px);
  font-family: var(--font-sans);
}
#changeset-drawer .changeset-modal {
  width: min(560px, 90vw); max-height: 70vh; overflow-y: auto;
  background: var(--bg-elevated); color: var(--text-primary);
  border: 1px solid var(--border-default); border-radius: var(--radius-lg);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}
#changeset-drawer .changeset-drawer__header {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--space-4); border-bottom: 1px solid var(--border-subtle);
  position: sticky; top: 0; background: var(--bg-elevated); z-index: 1;
}
#changeset-drawer .changeset-drawer__header-title { font-weight: 700; font-size: var(--font-size-md); color: var(--text-primary); }
#changeset-drawer .changeset-drawer__doc-row { padding: var(--space-2) var(--space-4); border-bottom: 1px solid var(--border-subtle); }
#changeset-drawer .changeset-drawer__doc-top { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
#changeset-drawer .changeset-drawer__doc-label {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: var(--font-size-sm); color: var(--text-primary);
}
#changeset-drawer .changeset-drawer__badges { flex-shrink: 0; display: flex; gap: var(--space-1); font-size: var(--font-size-xs); }
#changeset-drawer .changeset-drawer__badge { padding: 1px 6px; border-radius: var(--radius-sm); font-weight: 500; }
#changeset-drawer .changeset-drawer__badge--new,
#changeset-drawer .changeset-drawer__badge--changed { background: var(--bg-hover); color: var(--text-primary); }
#changeset-drawer .changeset-drawer__badge--none { background: var(--bg-hover); color: var(--text-muted); }
#changeset-drawer .changeset-drawer__badge--delete { background: var(--pending-dim); color: var(--pending); }
#changeset-drawer .changeset-drawer__conflict { margin-top: var(--space-1); color: var(--pending); font-size: var(--font-size-xs); }
#changeset-drawer .changeset-drawer__diff-toggle {
  background: transparent; border: none; color: var(--accent); font-size: var(--font-size-xs);
  cursor: pointer; padding: 2px 0; margin-top: var(--space-1); font-family: var(--font-sans);
}
#changeset-drawer .changeset-drawer__diff-block {
  display: none; margin-top: var(--space-2); padding: var(--space-2);
  background: var(--bg-base); border-radius: var(--radius-md);
  font-family: var(--font-mono); font-size: var(--font-size-xs); line-height: 1.4;
  overflow-x: auto; white-space: pre-wrap; color: var(--text-secondary);
}
#changeset-drawer .changeset-drawer__footer {
  padding: var(--space-3) var(--space-4); border-top: 1px solid var(--border-default);
  display: flex; justify-content: flex-end; gap: var(--space-2);
  position: sticky; bottom: 0; background: var(--bg-elevated); z-index: 1;
}

/* Toasts */
.toast-area {
  position: fixed; bottom: var(--space-5); right: var(--space-5); z-index: 2147483100;
  display: flex; flex-direction: column; gap: var(--space-2); pointer-events: none;
  font-family: var(--font-sans);
}
.toast-area .toast {
  display: flex; align-items: flex-start; gap: var(--space-3);
  padding: var(--space-3) var(--space-4); background: var(--bg-elevated);
  border: 1px solid var(--border-default); border-radius: var(--radius-md);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5); min-width: 240px; max-width: 360px;
  pointer-events: auto; animation: astraeus-toast-in 200ms ease forwards;
}
.toast-area .toast.is-leaving { animation: astraeus-toast-out 200ms ease forwards; }
@keyframes astraeus-toast-in {
  from { opacity: 0; transform: translateY(8px) scale(0.96); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes astraeus-toast-out {
  from { opacity: 1; transform: translateY(0) scale(1); }
  to { opacity: 0; transform: translateY(4px) scale(0.96); }
}
.toast-area .toast__icon { font-size: 14px; line-height: 1.5; flex-shrink: 0; color: var(--text-primary); }
.toast-area .toast__body { flex: 1; min-width: 0; }
.toast-area .toast__title { font-size: var(--font-size-sm); font-weight: 500; color: var(--text-primary); }
.toast-area .toast__msg { font-size: var(--font-size-xs); color: var(--text-secondary); margin-top: 1px; }
.toast-area .toast--success { border-left: 3px solid var(--green); }
.toast-area .toast--error { border-left: 3px solid var(--red); }
.toast-area .toast--info { border-left: 3px solid var(--accent); }
.toast-area .toast--warning { border-left: 3px solid var(--yellow); }
`

export const CHROME_CSS_TEXT = CHROME_CSS

/** Add the stylesheet to the page, once. */
export function injectChromeStyles(doc = document) {
  if (doc.getElementById('astraeus-embed-styles')) return
  const style = doc.createElement('style')
  style.id = 'astraeus-embed-styles'
  style.textContent = CHROME_CSS
  doc.head.appendChild(style)
}
