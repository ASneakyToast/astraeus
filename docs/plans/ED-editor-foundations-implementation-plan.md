# Editor Foundations — Implementation Plan

**ADRs:** [020 — One widget layer, two surfaces](../decisions/020-shared-widget-layer.md) ·
[021 — Editing transport and durability](../decisions/021-editing-transport-and-durability.md) ·
[022 — Touch as the base case](../decisions/022-touch-as-base-case.md)  
**Reference:** [Editor widget inventory](../editor-widgets.md)  
**Branch base:** `main` → new branch `feat/editor-foundations`  
**Status:** Ready for implementation  
**Date written:** 2026-09-20

---

## Overview

Make the fallback authoring surfaces good and reliable, and consolidate the widget layer that
both surfaces should have been built from. Six phases. ED-1 is a correctness fix with no visual
change and should land first regardless of what happens to the rest.

Scope is `starlette-editor` and `starlette-cms`, plus token adoption in
`starlette-cms-gateways` and `mediakit`.

---

## Dependency graph

```
ED-1 (durability)          ─── independent, land first
ED-2 (unblock small screens) ─ independent
ED-3 (tokens + promotion)  ─── independent start, needs ED-2 for target sizing
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
ED-4 (changeset panel merge)              ED-5 (shell IA + pending view)
                    └─────────────────┬─────────────────┘
                                      ▼
                            ED-6 (embed adoption + cleanup)
```

**Parallel starts:** ED-1, ED-2, and ED-3 have no dependency on each other. ED-1 is the
priority — it is the only phase that stops active data loss.

---

## ED-1 — Durability

**Packages:** `starlette-editor`  
**Complexity:** Medium  
**Blocks:** nothing  
**ADR:** 021

### Goal

No silent data loss in either surface. No visual change.

### Tasks

**ED-1A: Navigation guards**
- `standard/actions.js:selectDoc()` — check `state.isDirty` before wiping `formData`; prompt
  via the shared confirm widget
- `standard/actions.js:selectType()` — same
- Register a `beforeunload` handler in `index.js` that fires while `state.isDirty`
- Wire `components/confirm.js` as the confirm implementation (it currently has zero importers)

**ED-1B: Local draft buffer**
- New `editor_src/draft-buffer.js` — `save(docId, formData)` debounced, `load(docId)`,
  `clear(docId)`, all `localStorage`-backed and keyed by document id
- Write on every `onFieldChange`
- Clear on successful save and on explicit discard
- On `selectDoc`, if a buffer exists and is newer than the server copy, prompt to restore or
  discard
- Cap total buffer size; evict oldest on quota error rather than throwing

**ED-1C: Fix the collab reject handler**
- `embed/collab.js:160-164` — on `reject`, request missed steps, apply via `receiveTransaction`,
  let `prosemirror-collab` rebase pending steps. Remove the reconnect-as-recovery path
- Verify unconfirmed steps survive a version conflict and a brief socket drop

**ED-1D: Amend ADR 018**
- Mark §3's rewind/audit claims and the "conflict-free rebasing" line as superseded by ADR 021
- Audit `GET /api/documents/{id}/history` — it must not promise reconstruction it cannot do

### Test plan
- Unit: buffer save/load/clear/evict; dirty guard fires on both nav paths
- Unit: reject handler rebases rather than reconnecting
- Integration: edit → navigate away → prompted; edit → reload → offered restore
- Manual: edit on a phone, background the tab until evicted, return, restore

---

## ED-2 — Unblock small screens

**Packages:** `starlette-editor`  
**Complexity:** Small  
**Blocks:** ED-3 (target sizing)  
**ADR:** 022

### Goal

The shell is usable on a phone. Not redesigned — usable.

### Tasks

**ED-2A: Restore navigation**
- Remove `.sidebar-docs { display: none }` (`editor.css:1406`); make it a drawer below 640px

**ED-2B: Viewport and input fixes**
- `#app` → `100dvh` (`editor.css:93`)
- Raise the type scale floor to 16px for all inputs, textareas, and selects
- `env(safe-area-inset-bottom)` on the toolbar pill and any fixed bottom chrome

**ED-2C: Touch targets**
- 44×44px minimum under `pointer: coarse`, tightened under `(hover: hover) and (pointer: fine)`
- Known offenders: `editor.css:237` (24px), `:657` (28×26), `:1077` (`padding: 2px 4px`)

**ED-2D: Panels stop being desktop windows on small screens**
- Chat (360×540) and changeset (340×420) go full-width below 640px
- Disable `mousedown` drag and resize below 640px rather than leaving dead affordances

**ED-2E: Block reorder without drag**
- `components/block-canvas.js:207,333` — numbered rows with move controls, replacing
  `draggable` and the `dragstart`/`dragover`/`drop` handlers for all pointer types

### Test plan
- Unit: block move controls reorder correctly, including first/last edges
- Manual on device: select a document, edit every field type, save, publish
- Manual: confirm no input zoom on focus in iOS Safari

---

## ED-3 — Tokens and widget promotion

**Packages:** `starlette-cms`, `starlette-editor`, `starlette-cms-gateways`, `mediakit`  
**Complexity:** Large  
**Depends on:** ED-2  
**Blocks:** ED-4, ED-5  
**ADR:** 020

### Goal

One token file. Widgets live in `components/`. Dependency direction is one-way.

### Tasks

**ED-3A: Token stylesheet in `starlette-cms`**
- New stylesheet served by `starlette-cms`, consumed by all admin surfaces
- Colour, type scale (16px floor), spacing, radius, target sizes
- Type roles align with the consuming site's own faces where one is configured

**ED-3B: Adopt tokens**
- `editor.css` — replace the `:root` block
- `standard/changeset-panel-shell.js`, `embed/changeset-panel.js`, `embed/chat-panel.js` —
  replace hardcoded Catppuccin hex in `cssText`
- `starlette_cms_gateways/admin/routes.py:73` — replace the inline `<style>` palette
- `mediakit/static/admin.css:9-26` — replace the Bootstrap palette

**ED-3C: Fix the dependency direction**
- Promote `ChatPanel` from `embed/` to `components/`; remove the `index.js:17` back-import
- Add a lint rule or test asserting `standard/` and `embed/` never import each other

**ED-3D: Promote shell-only widgets**
- Move the field widgets in `standard/fields.js` into `components/`, per the inventory
- Add the missing containers: bottom sheet, bottom action bar

### Test plan
- Unit: existing JS suite passes after promotion
- Test: the cross-import assertion fails when a violation is introduced
- Visual: all four admin surfaces side by side, light and dark

---

## ED-4 — Changeset panel merge

**Packages:** `starlette-editor`  
**Complexity:** Large  
**Depends on:** ED-3  
**Blocks:** ED-6  
**ADR:** 020

### Goal

1,798 lines across two files become one component with a mounting variant.

### Tasks

**ED-4A: Build the merged component** in `components/`, taking the union in
[the inventory](../editor-widgets.md#the-changeset-panel-merge) — shell features (rename, move,
remove, discard, staged delete, orphaned drafts, inline diff, clear active) plus embed features
(Review & Publish confirm, unpublished-drafts list)

**ED-4B: Review & Publish becomes the publish flow for both surfaces** — no single-tap publish

**ED-4C: Keep `changeset-store.js` as the single source of active-changeset state**, including
adoption of a server-created changeset from the `x-changeset-id` PATCH response header

**ED-4D: Delete** `standard/changeset-panel-shell.js` and `embed/changeset-panel.js`

### Test plan
- Unit: port both existing test files; every behaviour in the union has a test
- Integration: publish, schedule, move between changesets, discard, staged delete
- Manual: the same changeset viewed from both surfaces shows the same state and actions

---

## ED-5 — Shell IA and pending view

**Packages:** `starlette-editor`  
**Complexity:** Large  
**Depends on:** ED-3  
**Blocks:** ED-6  
**ADR:** 022

### Goal

Three routes with back navigation. Pending view as the small-screen landing.

### Tasks

**ED-5A: Route stack** — type list → document list → editor, with history and back. Desktop
expands the stack into the existing three-column layout
**ED-5B: Pending view** — dirty and staged documents, publish and discard inline; default
landing below 640px
**ED-5C: Bottom action bar** — save, publish, overflow; inside the safe area. The toolbar pill
merges into it on small screens
**ED-5D: Document list search**

### Test plan
- Unit: route transitions, back behaviour, dirty guard interaction with routing
- Manual on device: the full triage loop — land on pending, open a document, fix, publish

---

## ED-6 — Embed adoption and cleanup

**Packages:** `starlette-editor`  
**Complexity:** Medium  
**Depends on:** ED-4, ED-5  
**ADR:** 020

### Goal

`embed/` consumes the shared layer. Duplicates deleted.

### Tasks

**ED-6A:** Point `embed/` at `prosemirror/mount.js`; delete `embed/prosemirror-embed.js`
**ED-6B:** Point `embed/` at `prosemirror/markdown.js`; drop the `markdown-it` dependency
**ED-6C:** Point `embed/` at `components/toast.js`; delete its local notice
**ED-6D:** Point `embed/` at `api.js` and `state.js`
**ED-6E:** Measure the `embed.js` bundle before and after; record it in the roadmap

### Test plan
- Unit: full JS suite
- Integration: inline editing on the live site — edit, save, publish, changeset
- Manual: bundle size did not regress

---

## Out of scope

- Server-side ProseMirror step application — non-goal per ADR 021 §5, with reopening conditions
- Offline editing
- `{type: "field"}` messages on the collab socket
- A native mediakit picker replacing the iframe
- `astraeus-portal` token adoption — the package is not in this repo yet

---

## Open questions

- **ProseMirror toolbar overflow at 44px targets** — needs a prototype during ED-2, not a
  decision on paper. May change ED-5's action bar design.
- **Does the pending view become the desktop default too?** Decide after using ED-5 on a phone.
- **`document_ref` picker** — sequence after ED-4, since it reuses the merged panel's document
  rows.
