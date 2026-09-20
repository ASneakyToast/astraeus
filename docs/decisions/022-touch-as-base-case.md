# ADR 022 — Touch as the base case

**Status:** Accepted  
**Date:** 2026-09-20

---

## Context

The editor shell is a three-column desktop IDE — type rail, document list, editor — with two
media queries in 1,400 lines of CSS. The narrow one deletes navigation:

```css
/* editor.css:1406 */
@media (max-width: 640px) {
  .sidebar-docs { display: none; }
}
```

`.sidebar-docs` is the only way to select a document. Below 640px the shell renders an icon
rail and an editor with nothing loaded into it, and no way to load anything.

The rest compounds it. `#app { height: 100vh }` (`editor.css:93`) with no `dvh` fallback. A
13px base and 12px labels (`editor.css:52`), so every input focus zooms the page on iOS, which
applies that behaviour below 16px. Touch targets at 24px (`editor.css:237`), 28×26px
(`editor.css:657`), and `padding: 2px 4px` (`editor.css:1077`). Block reordering is HTML5
drag-and-drop with no fallback (`block-canvas.js:207,333`), which is inert on touch. The
floating pill sits at `bottom: 24px` with no safe-area inset and a `mousedown`-only reposition
grip (`editor-toolbar.js:30,246`). The chat and changeset panels are fixed at 360×540 and
340×420, both draggable and resizable by `mousedown` only. The image picker opens the mediakit
admin in a `min(900px, 90vw)` iframe.

There are zero occurrences of `dvh`, `safe-area-inset`, `touch-action`, or `pointer: coarse` in
any hand-written CSS or JS in the repo.

None of this is a missing breakpoint. It is a desktop application that was squeezed.

---

## Decision

### 1. Small screens get triage, not authoring

The phone's job is to answer *what needs me* and let the user act — see what is dirty or staged,
fix a typo, approve a draft composed on desktop, drop in a photo, publish. Composition at length
is a desktop and inline-editing activity.

The small-screen shell therefore lands on a **pending view** by default: what has changed since
the last publish, with publish and discard reachable directly. Browsing by type is available,
not primary.

### 2. Three routes, not three columns

Navigation is a stack — type list → document list → editor — with real back navigation, rather
than three columns that shrink. Floating panels become bottom sheets. Primary actions live on
the bottom edge, inside `env(safe-area-inset-bottom)`.

The desktop three-column layout is what the stack *expands into* at width, not the canonical
form that mobile degrades from.

### 3. Touch is the base case in CSS

Target sizes, spacing, and hit areas are authored for touch and tightened for precise pointers
under `@media (hover: hover) and (pointer: fine)`, rather than the reverse. Minimum interactive
target is 44×44px. Every hover affordance has a non-hover equivalent; every `mousedown`
interaction has a pointer-event equivalent or an explicit-control alternative.

Layout uses `dvh`, never bare `vh`.

### 4. Controls degrade to explicit alternatives, never to nothing

Where an interaction cannot work on touch, it is replaced by an explicit control for all
users — not hidden on small screens. Block reordering becomes numbered rows with move
controls, which works with touch, keyboard, and screen readers, and removes the drag
dependency everywhere rather than maintaining two paths.

Nothing is `display: none` on small screens unless the same information is reachable by another
route on that screen.

### 5. Inputs are 16px minimum

All text inputs, textareas, and selects render at 16px or larger, to prevent iOS zoom-on-focus.
This is a floor on the type scale, not a per-field override.

---

## Rationale

**Why triage rather than a full mobile editor?**
Because a phone-sized IDE is bad at both jobs. Accepting that the 30-second interaction is the
real mobile use case lets the small-screen surface be good at something, instead of being a
worse version of the desktop surface. The shell remains complete — every control exists on
every screen size (decision 4) — but the default landing and the information hierarchy are
built for the common case.

**Why author for touch and tighten for mouse, rather than the usual direction?**
Because the failure is asymmetric. A 44px target is mildly loose with a mouse; a 24px target is
unusable with a thumb. Starting from the constrained case and relaxing is the direction that
cannot produce an unusable result.

**Why does this need an ADR rather than just being done?**
Because it is a standing constraint on all future widget work (ADR 020), and because the
temptation to add a breakpoint instead of rethinking a control is exactly how the current state
arose. Written down, it is a thing new widgets are checked against.

**Why replace drag-and-drop everywhere rather than adding a touch path alongside it?**
Two reorder implementations is two things to break. Explicit move controls are more accessible
than drag for keyboard and screen-reader users regardless of pointer type, so the touch fix and
the accessibility fix are the same change. Drag may return later as a pointer-fine enhancement
layered on top; it is not the primitive.

---

## Consequences

**Positive:**
- The shell becomes usable on a phone at all, which it currently is not below 640px
- Accessibility improves as a side effect: larger targets, non-hover affordances, keyboard-
  reachable reordering
- One token scale with a 16px floor removes a whole class of iOS zoom bugs

**Negative / tradeoffs:**
- Desktop information density drops. The current shell fits a lot on screen at 13px, and some
  of that is genuinely useful when working at length
- A 44px floor makes toolbars — particularly the ProseMirror toolbar — significantly wider,
  forcing overflow behaviour that does not exist today
- The pending view is a new surface to build and maintain, not a restyling of an existing one

**Neutral / deferred:**
- The mediakit admin iframe in the image picker is the worst remaining small-screen surface; it
  is addressed when mediakit adopts the shared tokens (ADR 020 §4), not here
- Light/dark preference for the admin surfaces
- Whether the pending view becomes the desktop default too

---

## Design History

1. 2026-09-20 — Initial draft, alongside ADR 020 and ADR 021, from the mobile audit of
   `/editor/shell`.
