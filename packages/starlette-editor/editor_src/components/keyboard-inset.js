/**
 * components/keyboard-inset.js — Keep fixed bottom chrome above the keyboard.
 *
 * The on-screen keyboard does not change the layout viewport, so anything
 * pinned with `position: fixed; bottom: 0` — the action bar holding Save — sits
 * underneath it. `env(safe-area-inset-bottom)` describes the home indicator,
 * not the keyboard, so it does not help.
 *
 * `visualViewport` does describe it: when the keyboard opens, the visual
 * viewport shrinks while the layout viewport does not, and the difference is
 * the keyboard's height. That difference is published as `--keyboard-inset` for
 * the stylesheet to add to its bottom offsets.
 *
 * Browsers without visualViewport keep an inset of 0, which is the behaviour
 * they had before.
 */

/** Trailing edge of the viewport, below which content is hidden by the keyboard. */
function keyboardHeight() {
  const vv = window.visualViewport;
  if (!vv) return 0;

  // Also subtract the offset, or a scrolled-away URL bar reads as keyboard.
  const hidden = window.innerHeight - vv.height - vv.offsetTop;
  return hidden > 0 ? Math.round(hidden) : 0;
}

/**
 * Publish the keyboard height as --keyboard-inset on <html>.
 *
 * Returns an unsubscribe so a test can tear it down; the shell never does.
 *
 * @returns {() => void}
 */
export function wireKeyboardInset() {
  const vv = window.visualViewport;
  if (!vv) return () => {};

  const apply = () => {
    document.documentElement.style.setProperty('--keyboard-inset', `${keyboardHeight()}px`);
  };

  apply();
  vv.addEventListener('resize', apply);
  vv.addEventListener('scroll', apply);

  return () => {
    vv.removeEventListener('resize', apply);
    vv.removeEventListener('scroll', apply);
    document.documentElement.style.removeProperty('--keyboard-inset');
  };
}
