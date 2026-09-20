# ADR 021 — Editing transport and durability

**Status:** Accepted  
**Date:** 2026-09-20  
**Amends:** [ADR 018](018-live-editing-north-star.md) (§3 "Step history", and the rebasing claim
under Rationale)

---

## Context

Two editing transports exist today and they have opposite failure modes.

**The shell uses explicit save over REST**, and loses work silently:

- `selectDoc()` and `selectType()` both wipe `formData` and reset `isDirty: false` with no
  guard (`standard/actions.js:38,69`). Selecting another document discards unsaved edits
  without a prompt.
- There is no `beforeunload` handler anywhere in `editor_src/`.
- There is no autosave and no local persistence — `formData` is in memory only.
- `isDirty` is tracked and surfaced as a 6px dot (`editor.css:376`).

**The embed uses the collab WebSocket**, and loses work on reconnect:

- `embed/collab.js:160-164` handles a `reject` by reconnecting, discarding pending local steps.
  The comment says "the simplest correct recovery is to reconnect." It is simple and it is not
  correct — `prosemirror-collab` exists precisely to rebase in this case, and the module already
  imports `receiveTransaction`.

Separately, the server authority does not do what ADR 018 describes.
`CollabAuthority.apply_steps()` (`starlette_cms/collab.py:57-96`) validates only that each step
is a dict carrying a non-empty `stepType` string, then assigns `self._doc = updated_doc` —
the client's post-edit document, taken on trust (`api/collab.py:198`). No steps are applied
server-side. ADR 018 claims "conflict-free rebasing (no last-write-wins data loss)"; what is
implemented is last-write-wins guarded by a version check.

`starlette_cms/prosemirror/bridge.py` is 198 lines and derives a ProseMirror *schema* from the
block registry. There is no Python document model and no step application to build on.

On a desktop these defects are survivable. On a phone they are the product: iOS evicts
backgrounded tabs aggressively, and cell/wifi handoff drops sockets routinely.

---

## Decision

### 1. Rebasing is the client's job, and the client will do it

`embed/collab.js` handles `reject` by requesting the steps it missed, applying them via
`receiveTransaction`, and letting `prosemirror-collab` rebase pending steps onto the new
version. Reconnection stops being the recovery path for a version conflict.

This is the canonical ProseMirror collab model: the server checks the version, applies, and
broadcasts; the client rebases. No server-side ProseMirror is required to get correct
convergence between honest clients.

### 2. Transport split by field kind

- **Rich text** (`field_type: rich_text`) streams over the collab WebSocket. The shell adopts
  this, matching the embed. `saveDocument()` already skips fields with a live collab
  connection, so the shell is half-migrated today.
- **Structured fields** (everything else — string, textarea, number, boolean, select, json,
  image, document_ref, block canvases) persist over REST `PATCH`. They are not ProseMirror
  documents; `prosemirror-collab` cannot rebase them, and encoding them as synthetic steps
  would poison the step log.

A `{type: "field", path, value, base_version}` message on the same socket is **deferred, not
rejected**. The authority is already document-scoped (`_doc` is the whole `draft_body`), so it
is a viable future unification. It is out of scope here because it buys real-time propagation
of structured-field edits, which nothing currently needs, and it costs a second conflict model.

### 3. A local draft buffer, independent of transport

Draft state persists to `localStorage`, keyed by document id, written on change (debounced).
On load, a buffer newer than the server's copy prompts the user to restore or discard.

This is **not offline editing**. It is crash survival for the reload and tab-eviction cases,
and it is the only durability story structured fields have at all, since they never touch the
collab socket. It is required regardless of which transport carries a field, which is why it
sits outside the transport decision rather than inside it.

### 4. Navigation guards

`selectDoc()` and `selectType()` check `state.isDirty` and prompt before discarding. A
`beforeunload` handler fires while dirty. Both use the shared confirm widget (ADR 020), not
`window.confirm`.

### 5. Server-side step application is a documented non-goal

The server continues to accept `updated_doc` on trust. ADR 018 §3's rewind and audit claims are
amended: `cms_steps` is an **advisory log of client-asserted steps**, not a verified history.
It is not sufficient to reconstruct document state, and `GET /api/documents/{id}/history` must
not promise that it can.

Reopen this decision when any of the following becomes true:

- A deployment exists with writers who are not trusted (the package is deployed by someone
  other than the author, or a third-party client gains write access)
- Verified rewind becomes a required feature rather than an aspiration
- Server `_doc` and peer-computed documents are observed to diverge in practice

---

## Rationale

**Why not implement server-side step application now?**
It buys trust and auditability, not convergence. Correct convergence between honest clients
comes from client-side rebasing (decision 1), which is a focused fix to one handler. Server-side
application additionally protects against a buggy or hostile client writing arbitrary content
while the version counter advances, and makes the step log reconstructable.

The cost is a Python ProseMirror document model and step application — `replace`,
`replaceAround`, `addMark`, `removeMark`, `addNodeMark`, `removeNodeMark`, `attr` — built from
zero, then kept in sync with ProseMirror's step format upstream. For the current deployment
(one human, one AI chat peer, the author's own site) that is a large permanent maintenance
commitment against a low-probability failure. For `starlette-cms` as a package others deploy it
is a genuine gap, which is why the reopening conditions are written down rather than left
implicit.

**Why write down a flaw instead of fixing it?**
Because ADR 018 currently overclaims, and an overclaiming ADR is worse than an honest one. Any
future reader — or agent — planning work against the step history needs to know it is advisory.

**Why is the local buffer separate from the transport decision?**
Because no socket survives a terminated tab, and no REST call survives one either. Durability
against process death is orthogonal to how bytes reach the server, and conflating the two is
what makes "just move everything to WebSocket" sound like a reliability fix when it is not.

**Why `localStorage` rather than IndexedDB?**
Draft bodies are JSON documents of a few KB. `localStorage` is synchronous, universally
available, and adequate at this size. IndexedDB becomes worth its complexity when buffering
media or exceeding the ~5MB quota; neither applies.

**Why keep structured fields on PATCH when the socket could carry them?**
Two conflict models on one socket is worse than two transports with clear boundaries. The
`field` message type remains available if real-time structured-field collaboration is ever
wanted; nothing here forecloses it.

---

## Consequences

**Positive:**
- Version conflicts stop losing work, and brief disconnections — tunnels, wifi handoff — become
  survivable for free, since `prosemirror-collab` holds unconfirmed steps in memory and rebases
  on reconnect
- The shell stops silently discarding edits on navigation
- A reload or tab eviction no longer destroys in-progress work
- ADR 018's claims match the implementation

**Negative / tradeoffs:**
- Two transports to reason about, with the boundary drawn at field kind
- The restore prompt is a new interruption in the load path, and a stale buffer that the user
  keeps dismissing is an annoyance to tune
- `cms_steps` keeps accumulating rows that are not trustworthy enough to rebuild from; the
  storage cost is real and the payoff deferred

**Neutral / deferred:**
- `{type: "field"}` messages on the collab socket
- Server-side step application, per the reopening conditions above
- Offline editing — explicitly out of scope; in-memory pending steps plus a local buffer cover
  the disconnection and crash cases, and nothing covers composing while genuinely offline
- Pruning or checkpointing `cms_steps`
- **Rebasing after a reconnect that missed steps.** Decision 1 covers the version-conflict case:
  the server broadcasts every accepted batch to all connections, so the broadcast that made us
  stale also carries what we need to rebase. It does not cover a client that was disconnected
  while the server advanced — that client's pending steps are based on a document the server no
  longer has, and the protocol has no way to ask for the steps in between. Adding one means
  reading them back out of `cms_steps`, which decision 5 leaves unverified and which the version
  collision below makes ambiguous. The client holds the steps and warns rather than silently
  diverging or silently dropping them; a real fix arrives with the reopening conditions in §5.
- **Version collision across publish cycles.** `draft_version` resets to 0 on publish
  (`documents.py:921,1041`, `changesets.py:310`) but `cms_steps` rows are never deleted — the
  only write to that table is an insert (`collab.py:120`). Version numbers therefore repeat, and
  `history_at_version` returns interleaved steps from every cycle, replayed over the *published*
  body as baseline when steps actually apply to `draft_body`. Not fixed here: the endpoint is
  advisory under decision 5, and a correct fix means either scoping steps by publish generation
  or clearing them on publish, which is a schema change that belongs with any future decision to
  make the log authoritative.

---

## Design History

1. 2026-09-20 — Initial draft. Written after tracing shell data loss to `actions.js` and embed
   data loss to the `reject` handler, and finding the authority does not apply steps.
