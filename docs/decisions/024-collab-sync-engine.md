# ADR 024 — Collaborative sync engine: step authority or CRDT

**Status:** Proposed — no decision yet. This ADR frames the choice, the criteria and the spike that
settles it. It reopens [ADR 021](021-editing-transport-and-durability.md) §5.
**Date:** 2026-10-03

> **Evidence labels.** **[repo]** read in this repository or reproduced locally; **[reported]** from
> a project page or search summary that was not read in full; **[verify]** not checked, and must be
> before this ADR is accepted; **[background]** general knowledge of ProseMirror and Yjs, not
> checked in this research. Unlabelled ratings in the Assessment table are my judgment and mostly
> rest on **[background]**. A decision should not rest on a **[verify]** or **[background]** line.

---

## Context

### What happened

Typing in the visual editor on the blog index duplicated characters, especially with autocorrect and
type-ahead. The cause was server-side: `CollabAuthority.apply_steps` returned one client ID for a
whole batch of steps, and `prosemirror-collab` pairs `clientIDs[i]` with `steps[i]`, so a sender
re-applied every step after the first **[repo]**. The text was then persisted, because the server
stores the client's post-edit document on trust (`api/collab.py`, ADR 021 §5) **[repo]**. Fixed in #34.

The bug is not the point. The point is what it exposed: the server cannot tell a correct document from
a corrupted one, because it never applies the steps it accepts. The fix was one line; **finding** it
took reading the client, the protocol and the server, because nothing server-side checked the result.

### Why ADR 021 §5 is due for reopening

ADR 021 §5 made server-side step application a non-goal and wrote down when to reopen it. One
condition is imminent and one is plausibly met; neither is proven:

| ADR 021 §5 reopening condition | Now |
|---|---|
| The package is deployed by someone other than the author | **Imminent, not yet met.** Astraeus is being dogfooded on joellithgow.com so it can be used on client projects; no client deployment exists yet. |
| Server `_doc` and peer-computed documents are observed to diverge | **Plausibly met, not observed.** The sender's document diverged from the intended edit and the server stored it; other peers would have received each step once. That is inferred from the code and a single-client reproduction, not seen between two live peers. |
| Verified rewind becomes a required feature | Open. ADR 018 §3 promises it; ADR 021 says it is not delivered. |

### Other debts that point the same way

From ADR 021's own *Neutral / deferred* list **[repo]**:

- A client that was disconnected while the server advanced cannot rebase its pending steps: the
  protocol has no way to fetch the steps in between. Today it keeps them and warns.
- `draft_version` resets on publish but `cms_steps` rows are never deleted, so version numbers
  repeat and `history_at_version` interleaves steps from different publish cycles.
- `cms_steps` is an advisory, client-asserted log, not a verified history.

### Constraints that shape any answer

1. **Mixed writers.** Humans (desktop and phone) and an AI peer edit the same field. `starlette-chat`
   builds its edits in Python (markdown → PM doc → `diff_docs` → replace steps) and submits them as
   client `claude-assistant` over the same WebSocket (`starlette_chat/diff.py`, `tools.py`, ADR 019) **[repo]**.
2. **Governed data.** Astraeus sells version history, authorship, approval and an audit trail
   (ADR 018 §3, 019 §3). Per-edit attribution is a product requirement, not a nicety.
3. **Python package, independently installable.** `starlette-cms` is a pip-installable Starlette
   package. ADR 019 rejected a Node subprocess for markdown → PM steps partly because it needs Node in
   the Python environment **[repo]**. Production already runs separate sidecars in k3s
   (the MCP servers, from the same Python image), so one more *deployed* service is not new; a Node
   *requirement of the package* would be.
4. **One datastore.** Prod persistence is `content.db` replicated by Litestream to R2. A second store
   for sync state would need its own backup story.
5. **Touch is the base case** (ADR 022): tabs get evicted, sockets drop on wifi/cell handoff.
6. **Draft/publish/changeset** semantics (ADR 018, 023) operate on `draft_body` as ProseMirror JSON.
   Whatever sync engine is used must keep that JSON available to the CMS, the API and the static site.

---

## Options

### A. Keep the step authority and make it verify

Keep `prosemirror-collab` (operational transformation by a central authority) and close the trust gap.

- **A1 — Python document model.** Implement ProseMirror step application in Python (`replace`,
  `replaceAround`, `addMark`, `removeMark`, node marks, `attr`), tracking ProseMirror's format
  upstream. ADR 021 already costed this as "a large permanent maintenance commitment" **[repo]**.
- **A2 — Authority in Node.** Run the step authority (or just step validation/application) in Node
  using the *same* `prosemirror-model`/`prosemirror-transform` as the client, so there is one
  implementation of the schema and the steps. The Python CMS stays the store.

### B. Yjs with Hocuspocus (Node server)

Replace `prosemirror-collab` with Yjs and the `y-prosemirror` binding; run a Hocuspocus server.

- Hocuspocus is an MIT Node WebSocket server for Yjs documents; 2.6k GitHub stars, ~14 open
  issues, actively developed, sponsored by Tiptap **[reported]**. A Database extension persists
  documents through your own `fetch`/`store` hooks as a binary Yjs update **[reported]**.
- `yDocToProsemirrorJSON` (from `y-prosemirror`) derives ProseMirror JSON on the server, so the CMS
  can keep `draft_body` as JSON **[reported]**. That JSON does not carry collaboration history, so the
  binary state must remain the source of truth **[reported]**.
- Scaling past one instance needs the Redis extension, which syncs instances but does not persist
  **[reported]**. Irrelevant at one replica.
- Client-side lock-in: I believe `HocuspocusProvider` is required rather than the stock
  `y-websocket` provider **[verify]**.

### C. Yjs with `pycrdt-websocket` (Python server)

Same client as B; the server is Python, in the CMS process or beside it.

- `pycrdt-websocket` syncs Yjs documents over WebSockets with rooms and a pluggable store (file or
  database); ~269 commits **[reported]**. The older `y-py`/`ypy-websocket` pair appears to be
  superseded by `pycrdt` and should not be used **[verify]**.
- Would keep the package pure Python (constraint 3) — but only if the open question below about deriving
  ProseMirror JSON in Python has a good answer.
- Open questions: ASGI/Starlette mounting; whether Python can turn a `y-prosemirror` XML fragment
  into schema-valid ProseMirror JSON without reimplementing the mapping; whether Python can *write*
  edits the binding will render correctly (relevant to the AI peer) **[verify all three]**.

### D. Managed services (Liveblocks, Tiptap Cloud)

Considered and set aside. Astraeus is a self-hosted, governed data platform that others deploy;
making a third-party service load-bearing for the core write path contradicts that.

---

## Criteria

1. **Convergence under concurrency** — humans and the AI peer, on flaky links.
2. **Server holds the truth** — the server's document is the merged result, not a client's claim
   (ADR 021 §5 conditions).
3. **Per-edit attribution** — who changed what, including `claude-assistant`.
4. **History between publishes** — rewind and audit, honest about what is verifiable.
5. **AI peer ergonomics** — cost of `starlette-chat` writing edits.
6. **Reconnect / missed updates** — the ADR 021 deferred gap.
7. **Persistence fit** — one datastore, Litestream, `draft_body` JSON for the CMS and site.
8. **Package independence** — what a client project must install and run.
9. **Maturity and lock-in** — of the engine and of the server layer.
10. **Migration cost** — editor, chat, history endpoints, existing documents, tests.
11. **Authorization** — who may edit which field. The current authority is scoped to one field per
    connection; a CRDT merges whatever update arrives. ADR 012 (multi-author permissions) and ADR 013
    (field-level access control) bear on this and were **not read for this draft [verify]**. It matters
    most for client projects.

---

## Assessment

Ratings are my reading of the evidence, not measurements. Cells with **?** are what the spike must
settle; they are not weaknesses of the option.

| Criterion | A1 Python PM model | A2 Node authority | B Hocuspocus | C pycrdt (Python) |
|---|---|---|---|---|
| 1 Convergence | Good: central order. Rejects and rebase churn under bursts | Good, same | Strong: CRDT merges without rejects | Strong, same engine as B |
| 2 Server holds truth | Strong once built | Strong: same code as client | Strong: server merges updates | Strong |
| 3 Attribution | Moderate: per-step client ID is stored, but it is client-asserted and not bound to the authenticated user | Moderate, same | **?** Updates are attributable per message; per-character authorship is not native | **?** same |
| 4 History | Log can become verified. Fix version-collision bug first | Same | **?** Needs snapshots; GC and undo-manager growth are known tensions **[reported]** | **?** same |
| 5 AI peer | Unchanged | Unchanged (Python still builds steps) | Needs a Node bridge or Yjs edits from Python | **?** Edits must produce what the binding renders |
| 6 Missed updates | Weak: needs step catch-up over a log with the collision bug | Same | Strong: state-vector sync is built in | Strong |
| 7 Persistence | Strong: existing tables | Strong | Moderate: new binary state; JSON derived | Moderate: same |
| 8 Package independence | Strong: pure Python | Weak: Node runtime | Weak: Node runtime | Strong *if* Python can derive PM JSON itself; otherwise it needs Node too |
| 9 Maturity / lock-in | `prosemirror-collab` is small and canonical. Python model has no upstream | Strong engine, bespoke glue | Yjs mature; Hocuspocus smaller, provider lock-in **[verify]** | Yjs mature; `pycrdt-websocket` **?** |
| 10 Migration cost | Low for editor and chat; **high** to build the model | Moderate | **High**: editor, chat, history, converting stored docs | **High**, but no Node |
| 11 Authorization | Existing per-field connection scoping carries over **[repo]** | Same | **?** Needs auth hooks and per-field documents or checks | **?** same |

Yjs itself: MIT, 22.9k GitHub stars, ~113 open issues, ~700k weekly downloads, used in production by
AFFiNE, Cargo, GitBook and Evernote; its README cites formal verification **[reported]**.

**Reported problems to read before accepting any Yjs option** (titles only — the threads were not
readable from the research environment **[verify]**): deletions made inaccessible by garbage
collection; undo manager disabling GC and unbounded document growth; snapshot history losing
deletions after refresh; and a thread titled "Random, rare data loss in production with
y-prosemirror". An XWiki forum thread about *removing* Hocuspocus also exists; its reason is unknown.

---

## What the evidence does and does not support

- **Supported:** the current design is the weakest on criteria 2 and 6, and those are the ones ADR 021
  said would trigger a rethink. Leaving §5 as written is hard to defend once the package is deployed for clients.
- **Supported:** A1 is the largest *permanent* cost, per ADR 021. It is the option least likely to be
  chosen on merit.
- **Not supported yet:** that Yjs beats a hardened step authority for *Astraeus*. Yjs wins on
  convergence and reconnect; it is unproven on attribution and verifiable history, which are the
  governed-data requirements. A CRDT that merges everything cannot by itself say a given edit was
  *wrong*; schema and policy validation still need a ProseMirror schema on the server side.
- **Open design question for B and C:** schema validation. Merged Yjs state can be structurally valid
  yet not a valid ProseMirror document. Something must check it on store.

---

## Proposed decision procedure

No option is chosen here. Run a time-boxed spike on **B and C** (the Yjs candidates) against the
current implementation plus **A2** as a hardened baseline, using one shared acceptance suite, then
write the deciding ADR (or amend this one before acceptance).

**Acceptance suite** (Playwright with the preinstalled Chromium for browser cases):

T1. **Autocorrect-style batches.** Multi-step edits in a real browser (the bug that started this).
T2. **Human + AI concurrency.** The AI peer rewrites a paragraph while a human types in it and in
   the next one; the result is deterministic and schema-valid.
T3. **Missed updates.** Client offline, server advances, client reconnects: no lost edits, no
   duplicates, no manual recovery.
T4. **Convergence fuzz.** Random concurrent edits across N replicas with random disconnects; all
   replicas equal at quiescence.
T5. **Durability.** Kill the server mid-edit; restart from a Litestream restore; no loss beyond the
   documented window.
T6. **Attribution.** For a sequence of human and AI edits, recover who made each, at what granularity.
T7. **History between publishes.** Rewind to a prior point; state the guarantees honestly.
T8. **Growth.** Document size after thousands of edits, with undo enabled.
T9. **JSON derivation.** `draft_body` JSON from the sync state validates against the ProseMirror schema
   and equals what the editor shows.
T10. **Publish cycle.** Draft → publish → next draft: versions and history stay coherent (this also
    exposes the existing version-collision bug).

**Exit criteria.** An option is viable only if it passes T1–T3, T5 and T9 and has a stated answer for T6–T8, and for criterion 11.
Between viable options, prefer the one that keeps the package pure Python, then the lower migration cost.

**Reading to finish first [verify]:** the ProseMirror collab guide (reference authority and per-step
client IDs); Hocuspocus hooks, auth and persistence docs; the Yjs forum threads named above;
`pycrdt-websocket` Starlette integration and its XML-fragment API.

---

## Consequences of proposing (not deciding)

- Nothing changes in production. The editor keeps `prosemirror-collab` with the #34 fix.
- The version-collision bug in ADR 021 stays open until this is decided; it is cheap to fix
  independently if the answer is A, and moot if the answer is Yjs.
- The spike costs a branch and real engineering time (not estimated here). Skipping it risks choosing on architecture taste, which is
  how the current design acquired its unverified claims.

---

## Design History

1. 2026-10-03 — Initial draft, written after the autocorrect duplication bug (#34) showed the server
   cannot detect a corrupted document. Research environment could not reach the Hocuspocus,
   ProseMirror and Yjs documentation sites, hence the evidence labels.
