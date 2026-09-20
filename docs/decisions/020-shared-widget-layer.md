# ADR 020 — One widget layer, two surfaces

**Status:** Accepted  
**Date:** 2026-09-20  
**Amends:** [ADR 018](018-live-editing-north-star.md) (§"What the existing admin SPA becomes")

---

## Context

ADR 018 established inline editing on the published site as the primary authoring UX and
demoted the admin shell (`/editor/shell`) to a fallback. That framing was correct about
priority and wrong about consequence: "fallback" was read as "lower standard," and the shell
drifted.

`editor_src/` is laid out as though both surfaces share a toolkit — `components/` and
`prosemirror/` sit above `standard/` (shell) and `embed/` (inline), alongside `api.js`,
`state.js`, `events.js`, and `changeset-store.js`. The structure is right. The wiring was
never done.

Actual importers of the shared layer, as of `fbce604`:

| Shared module | `standard/` | `embed/` |
|---|---|---|
| `api.js` | 4 | 0 |
| `state.js` | 5 | 0 |
| `events.js` | 1 | 0 |
| `components/toast.js` | 4 | 0 |
| `components/block-canvas.js` | 1 | 0 |
| `components/meta-panel.js` | 1 | 0 |
| `components/confirm.js` | 0 | 0 |
| `prosemirror/mount.js` | 3 | 0 |
| `prosemirror/markdown.js` | 1 | 0 |
| `changeset-store.js` | 4 | 1 |
| `components/image-picker.js` | 1 | 1 |
| `prosemirror/toolbar.js` | 1 | 3 |

`embed/` imports ProseMirror directly from npm and reimplements the mount in
`embed/prosemirror-embed.js`. It reimplements markdown with `markdown-it`. It reimplements
its own notice component. The changeset panel exists twice —
`standard/changeset-panel-shell.js` (1,184 lines) and `embed/changeset-panel.js` (614 lines).
`components/confirm.js` is dead.

The one place sharing happens, it runs backwards: `index.js:17` has the shell importing
`ChatPanel` from `./embed/chat-panel.js`.

This is why the admin surfaces have four unrelated visual languages (`editor.css` tokens,
Catppuccin hardcoded in both panels, Tailwind-ish greys in the gateways admin, Bootstrap 5 in
the mediakit admin). Nothing shares a widget, so nothing shares a token. The palette drift is
a symptom, not the disease.

---

## Decision

### 1. The shell is the reference implementation

The shell is where every control must exist, because it is the surface that cannot punt
anything to the live page — singletons, data-only blocks, JSON fields, documents with no
frontend representation, bulk operations. That makes it the only place that forces the
complete widget set to be solved.

Widgets are therefore built **in the shell first**, in `components/`, and `embed/` adopts
them. "Fallback" describes what the shell is *for*, not the standard it is held to.

### 2. Dependency direction is fixed and one-way

```
        components/  prosemirror/  api.js  state.js  events.js  changeset-store.js
                          ▲                    ▲
                          │                    │
                     standard/             embed/
```

`standard/` and `embed/` both depend on the shared layer. Neither imports the other. The
`index.js → embed/chat-panel.js` import is a violation and is removed by promoting
`ChatPanel` to `components/`.

### 3. A widget is shared by default

New controls land in `components/`. A surface-specific module is justified only by genuine
difference in *mounting* — where the widget attaches and what chrome surrounds it — never by
difference in behaviour or appearance. Where mounting genuinely differs, the widget takes a
variant argument rather than being forked.

### 4. One token file, owned by `starlette-cms`

Design tokens move out of `editor.css` into a standalone stylesheet served by `starlette-cms`
and consumed by every admin surface: the editor shell, the embed overlay chrome, the gateways
admin, the mediakit admin, and `astraeus-portal`. Inline `cssText` blocks with hardcoded hex
are replaced by token references.

Tokens are shared by construction once widgets are — this clause exists to stop the four
non-editor surfaces from drifting again while the widget work proceeds.

---

## Rationale

**Why make the fallback the reference implementation, when it isn't the primary UX?**
Because completeness runs the other way from priority. The inline editor gets to be selective —
if a field type is awkward on the page, it falls through to the shell. The shell has no
fallback of its own. Solving the widget set there means `embed/` inherits controls that are
already complete, already tested, and already work on touch; solving it in `embed/` first means
the shell keeps its gaps forever.

**Why not let the two surfaces diverge deliberately?**
That is the current state, and it produced 1,798 lines of changeset panel across two files
that do almost the same thing, with different subsets of features each. The shell can rename a
changeset, move documents between changesets, discard drafts, stage deletes, show orphaned
drafts, and view inline diffs. The embed can do a two-step Review & Publish confirm and add
drafts from a dedicated list. Neither is a superset. A user moving between the two surfaces
loses capabilities in both directions, unpredictably.

**Why does the token file belong to `starlette-cms` rather than `starlette-editor`?**
Because the gateways admin and `astraeus-portal` consume it too, and neither depends on
`starlette-editor`. `starlette-cms` is the only package all admin surfaces already depend on.
This follows the ADR 004 precedent: shared presentation knowledge lives in the package everyone
imports, activated rather than duplicated.

**Why not defer this until after the mobile work?**
The mobile work *is* this work. Rebuilding controls for touch means touching every widget. Doing
that without consolidating first means building each control twice, then consolidating a third
time.

---

## Consequences

**Positive:**
- One place to fix a control; both surfaces get the fix
- Tokens become shared as a side effect of widgets being shared, rather than as a separate
  discipline that has to be maintained
- The dead `components/confirm.js` gets a real consumer (the mobile confirm sheet)
- `embed/` loses its duplicate ProseMirror mount and markdown implementation, shrinking the
  bundle

**Negative / tradeoffs:**
- A widget shared between two surfaces is harder to change than one owned by a single surface;
  variant arguments accumulate if not policed
- The panel merge is a large single change to two files that are both currently working
- Short-term churn in `embed/`, which is the surface users actually touch today

**Neutral / deferred:**
- `astraeus-portal` is referenced by `joellithgow/pyproject.toml:29` at
  `../astraeus/packages/astraeus-portal` but does not exist in this repo or on any branch. It
  adopts the token file when it lands here.
- Whether `components/` eventually becomes its own publishable package — deferred; no consumer
  outside this repo yet.

---

## Design History

1. 2026-09-20 — Initial draft. Written after a mobile audit of the shell found the four-palette
   problem and traced it to the unwired shared layer.
