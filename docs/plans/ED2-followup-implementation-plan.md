# Editor Foundations — Follow-up Plan

**Follows:** [ED plan](ED-editor-foundations-implementation-plan.md) (ED-1 … ED-6, complete)
**ADRs:** [020](../decisions/020-shared-widget-layer.md) · [021](../decisions/021-editing-transport-and-durability.md) · [022](../decisions/022-touch-as-base-case.md)
**Branch base:** `main` → one branch per phase, each targeting `main`
**Status:** Awaiting approval
**Date written:** 2026-09-20

---

## What this covers

The six ED phases are merged. They were built from reading code and unit
tests — **none of it has run on a real phone**, which is where the complaint
that started this work came from. This plan validates that, pays down the test
debt that was pre-existing throughout, and closes the items ED deliberately
deferred.

## Delivery — three PRs, not fifteen

ED shipped in twelve PRs. Four of those existed only to unstick stacked
branches, and the rest were smaller than they needed to be. Three rules here:

1. **One PR per phase.** Grouped commits inside it, not separate PRs.
2. **Every branch from `main`, targeting `main`.** No stacks. Where phases
   touch the same files, they run in sequence, not in parallel.
3. **Merge commits, not rebase merges.** A rebase merge leaves the branch
   alive with different SHAs, which is what produced the add/add conflicts.

---

## Dependency graph

```
FU-1 (device pass)  ─── first; its findings shape FU-2
                              │
                              ▼
FU-2 (deferred UI work)  ─── depends on FU-1's toolbar decision
FU-3 (test debt)         ─── independent, can run any time
```

FU-3 has no dependency on either and can be pulled forward if the red suites
start costing more than they're worth.

---

## FU-1 — Run it on a phone and fix what's broken

**Packages:** `starlette-editor`, `mediakit`
**Complexity:** Medium, mostly unknown until it runs
**ADR:** 022

### Goal

Everything in ED-2 and ED-5 was reasoned about, not observed. This is the pass
that finds what reasoning missed.

### Tasks

**FU-1A: Drive the shell on a real device.** iOS Safari and Android Chrome, on
the actual deployed CMS. Walk the triage loop the design assumes: land on
pending, open a document, fix a typo, publish through review. Then the
authoring loop the design does *not* optimise for, to see how badly it fails:
create a document, fill every field type, reorder blocks, attach an image.

**FU-1B: Fix what the pass finds.** Two classes are near-certain and neither is
visible from the code:
- **Keyboard occlusion.** The virtual keyboard covers the bottom action bar and
  probably the field being edited. `env(safe-area-inset-bottom)` does not
  account for it; `visualViewport` does.
- **ProseMirror selection on touch.** Selection handles, the toolbar's relationship
  to the current selection, and whether formatting is reachable at all while the
  keyboard is up.

**FU-1C: Resolve the ProseMirror toolbar overflow.** The open question from
ADR 022. At 44px targets the button set does not fit 390px. Three candidates —
horizontal scroll, an overflow menu, or a contextual toolbar that appears on
selection. This has been explicitly waiting for a device, because it is a
question about thumbs and keyboards, not about CSS.

**FU-1D: The image picker on a phone.** Tokens made mediakit stop looking like a
different product, but it is still an iframe of a separate app inside a modal.
Judge whether that is usable on a phone or whether it needs the native picker
(FU-2C).

### Test plan
- Recorded walkthrough of both loops on both platforms
- Regression tests for each fix
- Unit tests pass

---

## FU-2 — Close the deferred UI items

**Packages:** `starlette-editor`, `mediakit`
**Complexity:** Medium
**Depends on:** FU-1
**ADR:** 020, 022

### Tasks

**FU-2A: `document_ref` picker.** `fields.js` renders it as a plain text input
with the comment "for now" — you type a document id by hand. Sequenced after
ED-4 because it reuses the merged panel's document-row rendering.

**FU-2B: Remaining embed `fetch` calls onto `api.js`.** `edit-mode.js` and
`toolbar.js` still call `fetch` directly for auth and document operations. Each
needs an `api.js` function added. ED-6 left this because it adds surface area
rather than deleting a duplicate — worth doing, but only alongside other work in
those files.

**FU-2C: Native media picker**, if FU-1D says the iframe fails on a phone.
A picker view against the mediakit API, replacing the iframe modal. This is the
largest single item here and is conditional on FU-1D.

### Test plan
- Unit tests for the picker and each new `api.js` function
- On a device: attach an image to a document end to end

---

## FU-3 — Pay down the pre-existing test debt

**Packages:** all
**Complexity:** Unknown until triaged
**Depends on:** nothing

### Goal

Every phase of ED reported "pre-existing failures, verified identical before and
after". That was true each time and it is not a good steady state: a red suite
means the next regression hides in the noise, and every change costs a
stash-and-compare to prove innocence.

### Tasks

**FU-3A: Triage.** Roughly 45 failures across four suites — 24 in `starlette-cms`
(23 of them `test_mcp_server.py`), 13 in `mediakit` (again mostly MCP), 5 in
`starlette-cms-gateways`, 3 in `starlette-editor`. The MCP concentration
suggests one or two shared causes rather than 45 independent bugs. Triage first,
then decide.

**FU-3B: Fix or delete, per test.** Some will be stale like the publish tests
were — asserting behaviour that was deliberately replaced. Those get rewritten
against what the code does or deleted. Others are real. Either outcome is fine;
what is not fine is leaving them red and unexamined.

**FU-3C: Green suites, and keep them green.** Once green, a red suite becomes
information again.

### Test plan
- `uv run pytest packages/` green
- `npm test` green
- Each fix names whether the test or the code was wrong

---

## Out of scope

- **Server-side ProseMirror step application** — non-goal per ADR 021 §5, with
  reopening conditions recorded there
- **`cms_steps` version collision** — documented in ADR 021; a correct fix means
  scoping steps by publish generation or clearing on publish, which is a schema
  change that belongs with any decision to make the step log authoritative
- **Offline editing**
- **The 16 stale agent worktrees** under `.claude/worktrees/` — housekeeping,
  not this plan

---

## Open questions

- **Does the pending view become the desktop landing too?** It was built for
  small screens. Decide after using it.
- **Should the built bundles stay in the repo?** `static/editor.js` and
  `static/embed.js` are committed esbuild output and conflicted on every
  parallel branch. Either keep committing them and always resolve by rebuilding,
  or build at package time and drop them from git. Worth settling before the
  next round of parallel work.
