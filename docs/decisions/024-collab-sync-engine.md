# ADR 024 — Collaborative sync engine: step authority or CRDT

**Status:** Proposed — no decision yet. This ADR frames the choice, the criteria and the spike that
settles it. It reopens [ADR 021](021-editing-transport-and-durability.md) §5.
**Date:** 2026-10-03

> **Evidence labels.**
> **[repo]** read in this repository (or reproduced locally, where it says so).
> **[checked: url]** read at that URL on 2026-10-03.
> **[reported]** from a search result or project page that was not read in full.
> **[inferred]** my reasoning from checked facts; not stated by any source.
> **[unchecked]** tried and not confirmed, or not attempted; the reason is given. A decision should not
> rest on a **[reported]** or **[unchecked]** line.
>
> **How the web was read.** Pages and raw source files were fetched through a tool that returns a
> model-written summary of the page, not the bytes. Quotations below are what that tool returned. For
> every load-bearing claim (marked in the Findings) the spike should re-read the source itself.
> Ratings in the Assessment table are my judgment; each cell cites the finding it rests on.

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

- **A1 — Authority in Python, on `prosemirror-py`.** Apply each accepted step server-side with a Python
  port of `prosemirror-model` and `prosemirror-transform`. **The first draft of this ADR, and ADR 021,
  priced this as building a Python document model "from zero". That premise is wrong:** a maintained
  port exists (F2). The cost is now a third-party dependency to vet and pin, a Python schema that must
  match the editor's, and the authority logic itself (F1), not a model.
- **A2 — Authority in Node.** Run the step authority (or just step validation/application) in Node
  using the *same* `prosemirror-model`/`prosemirror-transform` as the client, so there is one
  implementation of the schema and the steps. The Python CMS stays the store. A2 was attractive
  mainly because A1 looked expensive; F2 weakens that reason, and it still adds a Node requirement.

### B. Yjs with Hocuspocus (Node server)

Replace `prosemirror-collab` with Yjs and the `y-prosemirror` binding; run a Hocuspocus server. Facts
in F3–F5.

- MIT Node WebSocket server for Yjs, 2.6k stars, 14 open issues, maintained by ueberdosis and
  sponsored by Tiptap and others **[checked: https://github.com/ueberdosis/hocuspocus]**.
- Persistence is a binary Yjs update through `onLoadDocument`/`onStoreDocument` (or the Database
  extension). `yDocToProsemirrorJSON` derives ProseMirror JSON, but the JSON cannot be the source of truth
  (F5).
- **`HocuspocusProvider` is required.** Stock `y-websocket` does not work against Hocuspocus (F5).
- Scaling past one instance is out of scope at one replica; the docs' own advice is to split documents
  across independent instances, and they point to a Redis extension for HA **[checked:
  https://tiptap.dev/docs/hocuspocus/guides/scalability]**. Whether Redis persists is not stated there.

### C. Yjs with `pycrdt-websocket` (Python server)

Same Yjs data model; the server is Python, in the CMS process or beside it.

- **The client is not "the same as B".** B needs `HocuspocusProvider`; C needs a provider that speaks
  the plain y-websocket protocol, and I found no page confirming a stock JS `y-websocket` client works
  against `pycrdt-websocket` **[unchecked]** (F6).
- `pycrdt-websocket` 0.16.5 (Sep 2026, Project Jupyter, MIT) exposes an ASGI server with an
  `on_connect(message, scope)` hook, rooms keyed by path, and pluggable stores (F6).
- The older `y-py` / `ypy-websocket` pair is **not viable**: `ypy-websocket` is archived and says "This
  project is abandoned, please look at pycrdt-websocket" **[checked: https://github.com/y-crdt/ypy-websocket]**.
- Would keep the package pure Python (constraint 3) only if Python can read and write the
  `y-prosemirror` structure itself. `pycrdt` has the XML types but no ProseMirror conversion (F6).

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
11. **Authorization** — who may edit which field, and who can be stopped from editing. Today the collab
    socket enforces none of it (F7). It matters most for client projects.

---

## Findings from the evidence pass

Each finding says which options it moves and in which direction.

### F1. The reference authority versus ours

**[checked: https://prosemirror.net/docs/guides/collab/]** The guide's authority, in its own words,
applies each step on the server and keeps a client ID per step:

```javascript
receiveSteps(version, steps, clientID) {
  if (version != this.steps.length) return
  steps.forEach(step => {
    this.doc = step.apply(this.doc).doc
    this.steps.push(step)
    this.stepClientIDs.push(clientID)
  })
  ...
}
stepsSince(version) {
  return { steps: this.steps.slice(version), clientIDs: this.stepClientIDs.slice(version) }
}
```

The version is the length of the steps array; a client catches up by asking for `stepsSince(version)`.
The guide adds that "you'll probably also want your authority to start throwing away steps at some
point, so that its memory consumption doesn't grow without bound". It does not say anything about a
client that has fallen behind the truncation point, or about the server needing the schema.

Against `CollabAuthority` **[repo]** (`collab.py`, `api/collab.py`):

| | Guide's authority | `CollabAuthority` (after #34) |
|---|---|---|
| Applies steps | Yes (`step.apply`) | **No.** Checks `stepType` is a string, then stores the client's `doc` |
| Client ID | One per step | One per step since #34 (`[client_id] * len(steps)`) |
| Catch-up | `stepsSince(version)` | **None.** `cms_steps` rows exist but no message serves them |
| Source of truth | Server-computed doc | Client-asserted doc |

So the divergence is two things the guide's own sketch has and ours lacks: application, and catch-up.
Both were deliberate (ADR 021 §5) and both are what a hardened A1 or A2 would restore. **Strengthens A**:
the reference design already includes the missing parts, so A is "finish the canonical design", not a
new design.

### F2. A Python port of ProseMirror exists

**[checked: https://pypi.org/project/prosemirror/, https://github.com/fellowapp/prosemirror-py]**
`prosemirror` on PyPI (repo `fellowapp/prosemirror-py`, BSD-3-Clause, maintained by Fellow.app):

- Ports `prosemirror-model` 1.25.4, `prosemirror-transform` 1.11.0, `prosemirror-schema-basic` 1.2.4
  and the node specs of `prosemirror-schema-list` 1.5.1. **`collab` and `state` are not ported.**
- Exports `ReplaceStep`, `ReplaceAroundStep`, `AddMarkStep`, `RemoveMarkStep`, `AddNodeMarkStep`,
  `RemoveNodeMarkStep`, `AttrStep`, `DocAttrStep`, `Transform` and `Mapping` — the list ADR 021
  priced as unbuilt.
- "The full ProseMirror test suite has been translated and passes."
- Release history: 0.5.0 Apr 2024, 0.5.1 Nov 2024, 0.5.2 Mar 2025, **0.6.0 Feb 18 2026, 0.6.1 Feb 21
  2026**. 63 stars, 1 open issue, 339 commits.

**The repo does not use it** **[repo]**: nothing imports it. `starlette-chat` hand-rolls dict-level
`node_size`/`diff_docs` and `markdown_to_pm`.

Consequences:

- **A1's cost is restated, not removed.** What remains: vet a small single-vendor dependency; keep it
  within range of the editor's JS (`prosemirror-transform ^1.10` and `prosemirror-model ^1.22` in
  `starlette-editor/package.json` **[repo]**, against Python ports of 1.11.0 and 1.25.4); write the
  authority (F1); build a Python schema equal to the editor's (below). Whether the port's step JSON
  round-trips exactly with the client's current versions is **[unchecked]** — a spike test (T12).
- **The schema the editor uses is hard-coded in JS**, not fetched. `schema.js` builds
  `schemaWithLists` from `prosemirror-schema-basic` plus list nodes **[repo]**. The CMS's own
  `/api/editor-schema` (`prosemirror/bridge.py`) is generated separately and has no list nodes **[repo]**.
  A Python authority must reproduce the JS schema; `prosemirror-py` ports exactly those two schema
  packages, which makes that plausible **[inferred]**.
- **Weakens A2** (its main reason to exist was avoiding a Python model) and **weakens the claim that A is
  the largest permanent cost**.

### F3. `y-prosemirror` deletes content that does not fit the schema

This is the finding with the most weight on B and C.

**[checked: https://cdn.jsdelivr.net/npm/y-prosemirror@1.2.12/src/plugins/sync-plugin.js]**
`createNodeFromYElement` wraps node creation in a try/catch; on failure it deletes the element from the
Yjs document:

```javascript
} catch (e) {
  // an error occured while creating the node. This is probably
  // a result of a concurrent action.
  el.doc.transact((transaction) => { el._item.delete(transaction) }, ySyncPluginKey)
  mapping.delete(el)
  return null
}
```

**[checked: https://discuss.yjs.dev/t/random-rare-data-loss-in-production-with-y-prosemirror/3728]** The
maintainer (dmonad, 14 Aug 2025) on a "random, rare data loss" report (Yjs 13.6.14, y-prosemirror
1.2.12, roughly 1 in 100 users): "Concurrent edits can often lead to invalid schemas. For example: You
have a citation node which requires at least one paragraph… Two concurrent edits (each valid, deleting a
single paragraph) may result in a ProseMirror state with an invalid schema… y-prosemirror simply deletes
nodes that have an invalid schema (otherwise ProseMirror would throw an exception). I suggest removing
strict conditions from your schemas and possibly logging warnings when this happens." The thread was
**unresolved** at its last post (18 Nov 2025). Whether this explains the poster's losses is not
established; a second suspected cause (an event-handler error blocking later handlers, yjs issue #723)
was raised in the same thread.

Why it bites here:

- The editor's schema has strict content expressions: `doc: block+`, `blockquote: block+`, and list
  items that require a paragraph **[repo]** (`bridge.py`, `schema.js`). `doc: block+` is the same shape
  as the maintainer's example **[inferred]**; I did not reproduce a loss.
- The deletion happens in **whichever client renders the merged state first**, and it is a Yjs delete, so
  it replicates to everyone. The server (Hocuspocus or `pycrdt`) neither prevents nor notices it unless
  it also validates against the schema.
- The maintainer's remedy is to loosen the schema. That is in direct tension with this ADR's own
  requirement that something checks schema validity on store. **Weakens B and C on criterion 2** and
  makes a schema-validity test (T11) mandatory in the spike.
- Under A the schema is enforced when a step is applied, so an invalid step is rejected rather than
  merged and later deleted **[inferred]**.

### F4. Yjs history, GC and undo versus an audit trail

All **[checked]** at https://discuss.yjs.dev/ unless noted. None of these threads shows a fix; whether a
later Yjs release fixed any is **[unchecked]**.

- **#831 (Oct 2021–Jan 2022), version snapshots lose deletions after refresh.** Cause found by the
  poster: every `Y.Doc` created anywhere on the backend must have `gc: false`, including the one inside
  the persistence layer (`y-leveldb` created docs with defaults). Resolved by configuration.
- **#1839, GC and version snapshotting.** A team running millions of docs found `gc: false` "awful" for
  performance, disk and bandwidth, re-enabled GC on the backend, and kept snapshots only in the browser
  cache: "we no longer offer fully networked versioning". They accepted losing the persistent audit
  trail.
- **#537, compliance and data retention.** Keeping history while removing specific content is "very
  complicated and requires deep understanding of the internal structure of a Yjs document", via an
  undocumented `gcFilter`.
- **#3797 (Apr 2025), UndoManager disables GC, document size grows unbounded.** The undo manager keeps
  cleared items from ever being collected; dmonad: "GC will be disabled on those items forever. That is
  something that we could change", and that it would take him a while. Workarounds are user-written.

Reading: Yjs history is a trade between size and fidelity, and the editor has undo. For a product whose
selling point is an audit trail, **this weakens B and C on criterion 4** and makes T7 and T8 central, not
optional. It does not make rewind impossible; it means the guarantee has to be designed, and it is not
free.

### F5. Hocuspocus facts

**[checked: https://tiptap.dev/docs/hocuspocus/provider/overview]** "Hocuspocus comes with its own
provider and is not compatible anymore (since v2) with other y-providers, as we are supporting
multiplexing to synchronize multiple documents over the same websocket connection." and that "server
implementations apart from hocuspocus probably won't work too" with `HocuspocusProvider`. The draft's
open question is closed: **the provider is required.** It also means B and C cannot share a client.

**[checked: https://tiptap.dev/docs/hocuspocus/server/hooks]** Hooks relevant to us:

- `onAuthenticate` (gets `token`, headers, request, `documentName`; throwing closes the connection;
  `connection.readOnly = true` makes that connection read-only). Authorization is per connection and
  per document name, not per edit.
- `beforeHandleMessage` (gets the `update`; throwing closes the connection). It can reject a message; it
  cannot trim one.
- `onChange` (gets `update`, `context`, `transactionOrigin`; fires many times a second, debounce
  yourself). `onStoreDocument` is debounced and receives the whole document, not the updates; "If the
  hook throws, the document stays in memory and is retried".
- **[checked: https://tiptap.dev/docs/hocuspocus/server/configuration]** `debounce` 2000 ms and
  `maxDebounce` 10000 ms by default. That is the durability window for T5 unless lowered.
- **[checked: https://tiptap.dev/docs/hocuspocus/guides/persistence]** Documents are stored as the Yjs
  binary. "Do not store Y.Doc as JSON and recreate it as YJS binary upon user reconnection. This will
  cause issues with merging of updates and content will duplicate on new connections." So `draft_body`
  JSON is a **derived, one-way** projection.
- **[checked: https://tiptap.dev/docs/hocuspocus/server/examples]** `openDirectConnection(name)` with
  `transact(doc => …)` exists for server-side edits (the AI peer's candidate path). Whether such edits
  broadcast to clients and trigger `onStoreDocument` is **not stated in what I read [unchecked]**.

**[checked: https://forum.xwiki.org/t/switching-realtime-provider-removing-hocus-pocus/16867]** XWiki's
Cristal project (post by ClementEXWiki, 22 Apr 2025) listed why they were leaving: "Lots of
synchronization errors that seemingly come from nowhere", missing typing for events, "recurring troubles
with WebSocket which for some reason doesn't work reliably", "lack of configuration options", and no
clear signal for a failed initial connection. These are one project's experience of a different
integration; the thread does not diagnose any of them and I cannot say whether they apply to us.

**[checked: https://github.com/yjs/yjs]** Yjs: MIT, 22.9k stars, 114 open issues; users include AFFiNE,
Cargo, GitBook, Evernote, Linear, Proton Docs, among 40+. **Correction to the first draft:** the README
does not say Yjs is formally verified. It links `lean-yjs`, a third-party Lean formalisation of the YATA
algorithm that Yjs implements. That supports the algorithm, not the implementation, the binding or our
schema.

**[checked: https://github.com/yjs/y-prosemirror]** `main` of `y-prosemirror` now targets an unstable
`@y/prosemirror` on Yjs v14, and the README tells most users to stay on the 1.x line. A hand-written
Python reader/writer for the 1.x structure (F6) could need rework when v14 arrives **[inferred]**.

### F6. `pycrdt` and `pycrdt-websocket`

- `pycrdt` 0.14.8 (30 Sep 2026), "Development Status: Beta", MIT, Project Jupyter, wheels for
  manylinux/musllinux/ARM/macOS/Windows **[checked: https://pypi.org/project/pycrdt/]**.
- `pycrdt-websocket` 0.16.5 (20 Sep 2026), MIT, Python ≥3.10, depends on `pycrdt >=0.14.0,<0.15.0`
  and `pycrdt-store >=0.1.5,<0.2.0`; five releases in 2026 so far
  **[checked: https://pypi.org/project/pycrdt-websocket/, https://raw.githubusercontent.com/y-crdt/pycrdt-websocket/main/pyproject.toml]**.
  The tight `pycrdt` pin means every `pycrdt` minor needs a websocket release first.
- Mounting: `ASGIServer(websocket_server, on_connect=…, on_disconnect=…)` is a raw ASGI app that handles
  its own lifespan and passes `scope["path"]` to the connection; `on_connect(message, scope)` returns
  truthy to **refuse** the connection (headers and cookies are in `scope`)
  **[checked: https://raw.githubusercontent.com/y-crdt/pycrdt-websocket/main/src/pycrdt/websocket/asgi_server.py]**.
  How to mount it under Starlette next to the CMS app (lifespan nesting) is **[unchecked]**: the docs
  pages I could reach did not show it, and `/usage/` returned 404.
- **JS client interop is [unchecked].** The README and docs pages I could read describe a Python
  `WebsocketProvider` and do not mention a JavaScript `y-websocket` client either way.
- `pycrdt` XML types: `XmlFragment`, `XmlElement` (`tag`, `attributes`, `children`), `XmlText`
  (`insert`, `format`, `diff()` for formatted runs). **No ProseMirror conversion and no JSON export**
  **[checked: https://raw.githubusercontent.com/y-crdt/pycrdt/main/python/pycrdt/_xml.py]**.
- The structure the binding writes, from `y-prosemirror` 1.2.12 **[checked:
  https://cdn.jsdelivr.net/npm/y-prosemirror@1.2.12/src/lib.js and `sync-plugin.js`]**: an element per
  node, `nodeName` = the node type, element attributes = node attrs; text marks are attributes on
  `Y.XmlText` runs keyed by mark type name, with the mark's attrs as the value;
  `yXmlFragmentToProsemirrorJSON(fragment)` needs no schema. This is simple enough that a Python
  converter is plausible, but nobody ships one that I found **[reported]** (a web search for pycrdt +
  ProseMirror returned nothing relevant), and the write direction is unproven. T9 and T2 settle it.
- Stores: `pycrdt-store`'s `SQLiteYStore` writes to **its own** SQLite file (`db_path`, default
  `ystore.db`), appends each update (table `yupdates`) with a checkpoint table, and squashes after an
  inactivity interval (`squash_after_inactivity_of`; `document_ttl` is deprecated)
  **[checked: https://raw.githubusercontent.com/y-crdt/pycrdt-store/main/src/pycrdt/store/sqlite.py]**.
  Using it as-is is a second datastore (constraint 4). A custom store writing into `content.db` is
  possible in principle **[inferred]**. Squashing discards per-update granularity, which cuts against
  criterion 3.

### F7. Authorization today, and what a CRDT changes (criterion 11)

ADR 012 (identity + `permission` callable) and ADR 013 (field allowlists and `immutable`) are both
**Proposed, not Accepted** **[repo]**. In the code:

- There is **no `identity` or `permission` anywhere** in `starlette_cms` **[repo]** (searched).
- Only `immutable` exists, and it is enforced only in `PATCH` (`api/documents.py`, "Strip immutable fields
  before merge") **[repo]**.
- The collab socket checks one thing: `_check_ws_auth` (session cookie, API key or no auth). It then
  accepts **any** `field` query value; nothing checks that the field exists, is a rich-text field of this
  document type, or is not `immutable` **[repo]**, read in `api/collab.py`; not exercised against a
  running server. `_persist_steps` writes `{**body, field: doc}`, so an authenticated socket can write
  any key.
- Every collab edit is attributed to the client-supplied `clientID` string, not the authenticated user
  **[repo]**.

**Correction to the first draft:** it said the per-field connection scoping "carries over". That scoping
exists to keep two fields' steps apart, not to authorize anything, so there is nothing to carry over.
Criterion 11 is a gap in the *current* system, whichever engine is chosen.

What a CRDT changes **[inferred]**:

- A step authority can apply and judge each step before accepting it (reject a step touching a protected
  range, or from a user without the field). ADR 013's "silently strip disallowed fields" maps to
  per-field rooms plus per-connection permission, not to per-edit stripping.
- A CRDT server mostly sees opaque updates. Hocuspocus can refuse a connection, make it read-only, or
  reject a whole message (F5); `pycrdt-websocket` can refuse a connection by `scope` (F6). Neither lets you
  accept part of an update. Field-level rules therefore need one room per (document, field), as
  `collab_room` does today, plus a per-connection rule.
- Attribution comes from the authenticated connection (Hocuspocus `context`; `on_connect` scope), not from
  a client-asserted string. That is better than today for both A and B/C if ADR 012's `identity` lands.

### F8. What migration touches (the editor, chat and tests)

**[repo]**, counted by reading and `grep`:

- **Editor.** `collab.js` (270 lines) is the `prosemirror-collab` client: imports `collab`,
  `sendableSteps`, `receiveTransaction`, `getVersion`; plus `collab-sync.js`, `prosemirror/mount.js`,
  `embed/prosemirror-embed.js`. `schema.js` documents that both surfaces must share one schema because
  "prosemirror-collab can only apply a step if both ends agree on the schema". Five JS test files mention
  collab (`collab.test.js`, `collab-sync.test.js`, `api.test.js`, `nav-guard.test.js`,
  `module-boundaries.test.js`). The editor imports no undo module directly; `mount.js` uses
  `exampleSetup`, which I expect supplies `prosemirror-history` **[inferred]**. Moving to Yjs means
  `yUndoPlugin` and the F4 growth issue.
- **CMS.** `collab.py`, `api/collab.py` (542 lines), the `CMSStep` table and the history endpoints in
  `api/documents.py`; four CMS test files exercise collab (`test_collab.py`, `test_collab_peers.py`,
  `test_changesets.py`, `test_webhooks.py`), two more touch `cms_steps` (`test_documents.py`,
  `test_migrations.py`), and two chat test files (`test_integration.py`, `test_backend.py`) use the socket.
- **Chat.** `diff.py` (137 lines) emits block-level `ReplaceStep` dicts in reverse order against dict
  documents, and `tools.py` sends them with `"doc": new_doc` and `clientID: "claude-assistant"`. Under
  any Yjs option these steps are useless: the AI peer needs a Yjs write path (Hocuspocus
  `openDirectConnection`, or `pycrdt` XML edits), and `diff_docs` has to be rewritten against Yjs types.
  Under A it is unchanged, and (new) could be tightened to produce steps from a real `Transform`.

Neither the chat package nor the editor assumes `prosemirror-collab` beyond the above; I found no
additional coupling that raises the migration cost beyond what the Assessment already says. The one
under-priced item is the AI write path under B and C.

### F9. Existing trust gaps seen while reading (not fixed here)

These are not caused by any option; each is the same kind of gap as #34, and each is a candidate for a
separate fix **[repo]**:

- The AI peer sends `"doc": new_doc` with its steps and the server stores that doc unchecked. If
  `diff_docs` ever emits steps that do not produce `new_doc`, human clients apply the steps while the
  server persists `new_doc`.
- `api/collab.py` swallows persistence failures (`except Exception: pass`) after advancing the in-memory
  version, so a failed DB write is invisible and the version in memory runs ahead of `draft_version`.
- The socket accepts any `field` (F7).

### F10. Figma as a reference point for Path A

Added after the first evidence pass, at Joel's request. **[checked]** at Figma's own posts, read through
the same summarising fetch tool as everything else (no outside commentary was read):
https://www.figma.com/blog/how-figmas-multiplayer-technology-works/ (Oct 2019),
https://www.figma.com/blog/making-multiplayer-more-reliable/ (Oct 2022),
https://www.figma.com/blog/rust-in-production-at-figma/ (May 2018),
https://www.figma.com/blog/multiplayer-editing-in-figma/ (Sep 2016).

- **Central authority, not a CRDT.** Figma rejected OT as "unnecessarily complex for our problem space" and
  says "Figma isn't using true CRDTs… Since Figma is centralized (our server is the central authority), we
  can simplify our system." The server keeps the latest value any client sent for each property of each
  object.
- **Conflicts are last-writer-wins per property.** Same property on the same object: the last value to
  reach the server wins. Clients apply their own change at once and ignore conflicting server echoes until
  it is confirmed.
- **The server rejects invalid changes** (for example a parent change that would create a cycle in the
  document tree). Child order uses fractional indexes.
- **Reconnect:** the client downloads a fresh copy and reapplies its offline edits on top.
- **Durability:** state lives in memory with a checkpoint every 30–60 s, plus (since 2022) a journal in
  DynamoDB of incremental changes, each with a per-file incrementing sequence number. After a crash the
  latest checkpoint is loaded and journal entries with higher sequence numbers are replayed. Figma reports
  95% of edits saved within about 600 ms, a goal of under 1 s of loss, and over 2.2 billion changes a day.
- **One process per document** (a Rust child process per document under a Node server, 2018).

What this does and does not tell us:

- **Supports** that a centrally ordered, server-validated design can be very smooth at scale, and that
  its authors chose it over both OT and a full CRDT. It is the same shape as option A.
- **Does not transfer:** the conflict rule. Property-level last-writer-wins suits independent properties
  such as position or fill; two people typing in one paragraph need step rebasing. How Figma merges text
  inside a text layer is **[unchecked]**; the posts I read do not say.
- **Transfers directly:** a numbered journal (what `cms_steps` would become once the publish-cycle
  version collision is fixed), server-side rejection of invalid changes (F1, F3), catch-up by loading a
  known point and replaying later entries (F1, criterion 6), and a stated durability target to measure
  T5 against (Hocuspocus defaults are 2 s / 10 s, F5).
- **A hybrid is already implied:** ADR 021 §2 keeps structured fields (title, tags, selects) on REST
  `PATCH` and defers a `{type: "field"}` socket message, which is the property-level model. Rich text
  would stay on step rebasing **[inferred]**.
- **Public delivery is untouched by any option.** The static site reads only published `body`; edits go
  to `draft_body` and reach the site on publish (ADR 018 §1, 023). The sync engine is part of the editing
  path only **[repo]**.

---

## Assessment

Ratings are my reading of the evidence, not measurements. Cells with **?** are what the spike must
settle; they are not weaknesses of the option. "F#" points at the finding the cell rests on.

| Criterion | A1 Authority in Python (`prosemirror-py`) | A2 Node authority | B Hocuspocus | C pycrdt (Python) |
|---|---|---|---|---|
| 1 Convergence | Good: central order. Rejects and rebase churn under bursts | Good, same | Strong at the Yjs level. At the ProseMirror level, merged state can violate the schema and the binding then deletes content (F3) | Same engine, same caveat (F3) |
| 2 Server holds truth | Strong, and shown by the spike: steps are applied and checked (F1; spike T9, T11, T12) | Strong: same code as client | **Weaker than the draft said.** Server holds a merged Yjs state; nothing checks it is a valid PM document unless added (F3) | Same, and a validator would be `prosemirror-py` (F2), so C needs it too |
| 3 Attribution | Per-step ID is stored. Today client-asserted; can be bound to the authenticated user (F7) | Same | **?** Per update via `onChange` context; `onStoreDocument` sees only state, debounced 2 s/10 s (F5). Per-character authorship is not native | **?** Per update at write; squashing discards it (F6) |
| 4 History | Log can become verified. Fix version-collision bug first | Same | **Weakened.** Snapshots need `gc:false` everywhere, which one large team abandoned; undo manager blocks GC (F4) | Same (F4); `pycrdt-store` squashes (F6) |
| 5 AI peer | Unchanged (could use a real `Transform`) | Unchanged | Needs a Yjs write path: `openDirectConnection`, broadcast behavior **[unchecked]** (F5) | **?** XML insert/format API exists (F6); result must render in the binding |
| 6 Missed updates | Weak on `main`. The spike's `catch_up` fixes it with real clients (T3) over an in-memory log; a durable log still needs a schema change (spike F16) | Same | Strong: state-vector sync is built in | Strong |
| 7 Persistence | Strong: existing tables | Strong | Moderate: binary state is truth, JSON one-way and must not be re-hydrated (F5) | Moderate: store must write into `content.db`; default is a second SQLite file (F6) |
| 8 Package independence | Strong: no Node, plus one small dependency that needs compiled `lxml` (F2, spike F11) | Weak: Node runtime | Weak: Node runtime | Python server; needs `prosemirror-py` for validation (F2) and a hand-written JSON reader/writer (F6), tight `pycrdt` pin |
| 9 Maturity / lock-in | `prosemirror-collab` is small and canonical (F1). `prosemirror-py`: one vendor, 63 stars, 11-month gap between 0.5.2 and 0.6.0 (F2) | Strong engine, bespoke glue | Yjs very mature; Hocuspocus smaller and **provider lock-in confirmed**; one project left it (F5) | Yjs mature; `pycrdt` Beta, `pycrdt-websocket` 0.x with a tight pin (F6) |
| 10 Migration cost | **Low to moderate**, measured: about 60 editor lines, 290 server lines, 18 chat lines, plus the durable log and identity work (F2, F8, spike) | Moderate | **High**: editor, history, chat write path, stored docs, tests (F8) | **High**, no Node, plus JSON converter |
| 11 Authorization | Gap today (F7). Per-step judgment is possible | Same | Connection-level hooks only; one room per field (F5, F7) | Connection-level `on_connect` only (F6, F7) |

---

## What the evidence does and does not support

- **Supported:** the current design is the weakest on criteria 2 and 6, and those are the ones ADR 021
  said would trigger a rethink. Leaving §5 as written is hard to defend once the package is deployed for
  clients. The reference design already contains the missing pieces (F1).
- **Changed:** A1 is no longer "the largest permanent cost". ADR 021's premise (a Python model built from
  zero) was not true on 2026-10-03: a maintained port with the upstream tests exists (F2). A1 became
  cheaper; A2 lost most of its reason to exist. The remaining A1 risks are dependency risk and version
  skew with the editor's JS, which are testable.
- **Strengthened against the Yjs options on the governed-data criteria (2, 3, 4):** the binding deletes
  schema-invalid merged content, and the maintainer's remedy is a weaker schema (F3); Yjs's audit-trail
  story is a size-versus-fidelity trade that a large team resolved against fidelity (F4). These do not
  make Yjs unusable, but they land exactly on the requirements this product sells.
- **Still true for the Yjs options:** convergence on bad links and reconnect (criteria 1 and 6) are
  where they are clearly better, and a hardened A still has OT's rejects under bursts.
- **Not viable, as framed:** (1) C with `HocuspocusProvider`, and any plan that assumes B and C share a
  client (F5); (2) `y-py`/`ypy-websocket` as the Python Yjs stack (F6); (3) A1 as "build the model from
  zero" (F2) — that is superseded, not unviable.
- **Not decided:** nothing here picks an option. No source made an option unusable on its own; B and C
  each carry unresolved questions the spike must answer (F3, F6).
- **Open design question for B and C:** schema validation. Merged Yjs state can be structurally valid
  yet not a valid ProseMirror document, and the binding may delete it before a server check runs (F3).

---

## Proposed decision procedure

No option is chosen here. *Update: the Path A1 spike has been run at Joel's request; its results are in the
next section. B and C have not been built.* Run a time-boxed spike on **B and C** (the Yjs candidates) against a hardened
step authority as baseline — now **A1 on `prosemirror-py`**, with A2 kept only if A1's conformance test
(T12) fails — using one shared acceptance suite, then write the deciding ADR (or amend this one before
acceptance).

**Acceptance suite** (Playwright with the preinstalled Chromium for browser cases):

T1. **Autocorrect-style batches.** Multi-step edits in a real browser (the bug that started this).
T2. **Human + AI concurrency.** The AI peer rewrites a paragraph while a human types in it and in
   the next one; the result is deterministic and schema-valid.
T3. **Missed updates.** Client offline, server advances, client reconnects: no lost edits, no
   duplicates, no manual recovery.
T4. **Convergence fuzz.** Random concurrent edits across N replicas with random disconnects; all
   replicas equal at quiescence.
T5. **Durability.** Kill the server mid-edit; restart from a Litestream restore; no loss beyond the
   documented window (Hocuspocus defaults are 2 s / 10 s, F5).
T6. **Attribution.** For a sequence of human and AI edits, recover who made each, at what granularity.
T7. **History between publishes.** Rewind to a prior point; state the guarantees honestly.
T8. **Growth.** Document size after thousands of edits, with undo enabled (F4).
T9. **JSON derivation.** `draft_body` JSON from the sync state validates against the ProseMirror schema
   and equals what the editor shows.
T10. **Publish cycle.** Draft → publish → next draft: versions and history stay coherent (this also
    exposes the existing version-collision bug).
T11. **Schema-invalid merge.** Two concurrent edits, each valid, that together violate the schema
    (for example both clients delete the last two paragraphs, against `doc: block+`, or the only
    paragraph in a list item). Record what each option does to the content and who notices (F3).
T12. **Step conformance.** Steps produced by the editor's current `prosemirror-transform` apply in
    `prosemirror-py` to the same document, for every step type the editor can emit (F2).
T13. **Authorization.** A connection without rights to a field cannot change it; an edit to an
    `immutable` field is refused; attribution is the authenticated user (F7).

**Exit criteria.** An option is viable only if it passes T1–T3, T5, T9 and T11 and has a stated answer for
T6–T8, T13 and criterion 11.
**Tie-break between viable options: not set.** The first draft preferred "pure Python, then lower
migration cost". That was my guess at a weighting and Joel has not confirmed it; the weights are an open
question for Joel (see the reply that accompanies this change), and this section should be filled in
from his answer.

**Stated leaning (2026-10-03), not a decision:** after reading the plain-language walkthrough of this ADR
and the Figma comparison (F10), Joel said he agrees with Path A. He has not yet given the criteria
weights, so this records a leaning only; the spike and the deciding ADR still stand.

**Still to read before a spike on B or C (everything else on the original list is done):**

- Whether a stock JS `y-websocket` client interoperates with `pycrdt-websocket`, and how to mount its
  ASGI server and lifespan beside the CMS app (F6).
- Whether Hocuspocus `openDirectConnection().transact` broadcasts to clients and triggers
  `onStoreDocument` (F5).
- Whether any Yjs release since April 2025 changed the UndoManager/GC behavior in #3797 (F4), and whether
  `y-prosemirror` has changed the delete-on-invalid behavior (F3).
- Whether `prosemirror-py` 0.6.1 is current against `prosemirror-model` / `prosemirror-transform` latest (F2).
- Source of the XWiki problems beyond their post (F5): the thread names symptoms, not causes.

---

## Spike results: Path A1 (server-side step application on `prosemirror-py`)

Run 2026-10-03 at Joel's request, as the time-boxed spike this ADR proposed, on the branch
`claude/adr-024-evidence-verify-tae1du` of `asneakytoast/astraeus` (not merged; four commits on top of
`a4ba3d2`: `0379739` chat fixes, `69a090c` server verification, `e89555c` editor client, `b4b8c2a` harness). It tests **only Path A1**. B and C were not built, so nothing below compares A to the Yjs
options; it says how far A1 gets and what it cost to get there. Status of this ADR is unchanged: Proposed.

### What was built

- **Verification (opt-in).** `CMS(verify_collab=True)` makes `CollabAuthority` apply every step to its own
  copy of the field with `prosemirror-py` and store the document the steps produce. The client's claimed
  document is compared and logged (`collab_doc_mismatch`), never stored. A batch whose steps do not parse,
  do not apply, or would leave a node with content its schema forbids is refused whole. The `collab-verify`
  extra installs `prosemirror>=0.6.1,<0.7`. Default behaviour is unchanged.
- **Catch-up.** A client sends `{type: "catch_up", version}` and gets the steps after that version, one sender
  per step, as an ordinary `steps` message; or `resync_required` when the server cannot serve them.
- **Socket hardening in verifying mode.** The `field` must be a rich-text field the block type defines and
  must not be `immutable`; a failed database write is reported to the client; unexpected exceptions in the
  socket handler are logged instead of swallowed.
- **Client.** `CollabConnection` asks for the missed steps on reconnect instead of warning, and checks the
  version of every incoming batch (below, F14).
- **Fixes found on the way, outside Path A (F12).** The AI peer's block positions and mark names.
- **Harness.** A browser-less end-to-end harness that drives the editor's real `CollabConnection` and
  `prosemirror-collab` against a live uvicorn server (`packages/starlette-editor/scripts/e2e-collab.mjs`,
  server in `packages/starlette-cms/tests/e2e/serve_collab.py`), in three server modes: `verify`, `legacy`
  (today's `main`) and `bug34` (legacy with the #34 bug put back).

### Results against the acceptance suite

| Test | Result | Evidence |
|---|---|---|
| T1 autocorrect-style batches | **Pass** | In-process: a batch is applied server-side with one sender ID per step. Real client: `verify` passes on every run. `bug34` mode reproduces the original duplication (`the⟦t1⟧the⟦t1⟧⟦t1⟧`), so the harness would have caught #34. |
| T2 human + AI concurrency | **Partial** | The AI peer's steps now apply on the server to exactly the document it claims: 200 seeded random rewrites over 12 block kinds. Two bugs found and fixed to get there (F12). A real concurrent AI peer against live human typing, including `tools.py`'s reconnect-and-re-diff, was not run. |
| T3 missed updates | **Pass** (`verify`), **fail** (`legacy`) | A tab edits offline while another advances the server, then reconnects: `verify` converges with every edit present once. On `legacy` the offline edits stay pending forever and the server never receives them. |
| T4 convergence fuzz | **Pass** (`verify`), **fail** (`legacy`) | 4 tabs, about 300 random operations each run (insert, delete, mark, split, join, autocorrect batches), random disconnects, 8 seeds: all tabs and the server end on the same document and no insertion is duplicated. `legacy` does not converge. |
| T5 durability | **Partial** | A restarted authority reloads the server's document and version from the database (test). A failed write is now reported. The acknowledgement is sent after the database write (code read). Killing the server and restoring from Litestream was **not run**. |
| T6 attribution | **Not run** | Nothing to run against: step IDs are still client-asserted, and no `identity` hook exists (F7). |
| T7 history between publishes | **Not run** | The catch-up log is in memory (F16); `cms_steps` is unchanged. |
| T8 growth | **Not measured** | No CRDT growth question applies to A. The in-memory log is capped at 5000 steps; `cms_steps` rows are still never pruned. |
| T9 JSON derivation | **Pass** | The stored `draft_body` field is the server-computed document and validates against the schema. |
| T10 publish cycle | **Partial** | Editing after a publish works while the authority is alive. A server restart between a publish and the next edit reloads the reset version (0) while clients still hold the old one; a client with pending edits then gets `resync_required`. The ADR 021 version-collision flaw, not fixed here (F16). |
| T11 schema-invalid merge | **Pass** | Two erases that are each valid (either line of a two-line quote box) are accepted alone; the second one applied after the first is refused with `Invalid content for node blockquote`. Nothing is merged and later deleted. |
| T12 step conformance | **Pass** | 23 batches built with the editor's own `prosemirror-transform` reach the same document in `prosemirror-py`. See F11. |
| T13 authorization | **Partial** | A field that is not an editable rich-text field of the block type is refused with close code 4403. Binding edits to the authenticated user is **not** done: it needs ADR 012. |

### Findings from the spike

**F11. `prosemirror-py` held up, with three qualifiers.**
All 23 fixtures pass (steps: `replace`, `replaceAround`, `addMark`, `removeMark`, `attr`) although the
editor resolves `prosemirror-transform` 1.12.2 and `prosemirror-model` 1.25.12 against the port's 1.11.0 and
1.25.4. `addNodeMark`, `removeNodeMark` and `docAttr` are not covered because the editor's schema does not
emit them. (1) The package depends on `lxml` and `cssselect`, so "pure Python" needs a footnote: `lxml` is a
compiled extension with wheels for common platforms. (2) Applying a step that would leave a node with invalid
content **raises** `ValueError` instead of returning a failed result, so a verifier must catch exceptions as
well as check `failed`. (3) Its last release was Feb 2026; the skew above is a standing risk that T12 now
measures.

**F12. The AI peer's edit path did not work against a real editor.**
Found by T2 and confirmed against the real JavaScript `prosemirror-model`, not just the Python port.
(a) `diff_docs` counted block positions from 1; ProseMirror's document content starts at 0, so the first
block starts at 0. A replace of the last block reached past the end of the document and threw
`RangeError: Position 15 out of range`; shifting by one made it apply correctly. (b) `markdown_to_pm` emitted
the marks `bold` and `italic`; the editor's schema calls them `strong` and `em`, so a document containing
them throws on `nodeFromJSON`. The existing tests encoded both mistakes ("from should be 1 (start of first
block)", `{"type": "bold"}`), and the server accepted anything, so nothing failed. Both are fixed on the
spike branch. Consequence **[inferred]**: AI edits would have failed to apply in live editors while the
server stored the document the AI claimed, so they would appear after a reload; that fits the original
"the server cannot tell" finding and is exactly what server-side application catches.

**F13. A real-client harness separates the three server states.**
Driving the editor's real classes, `verify` passed T1, T3 and T4 on all 8 seeds; `legacy` failed T3 and T4 on
all 3 seeds tried (it passes T1, because #34 is fixed); `bug34` failed all three scenarios on both seeds
tried, T1 with the original duplication. It is a Node process with Node's
WebSocket, not a browser, so it does not cover the DOM, input events or the editor's rendering.

**F14. Reconnecting needs the client to check versions, not only the server to serve steps.**
`prosemirror-collab` counts steps and does not know which version a step belongs to. After a reconnect the
server registers a tab for live broadcasts before its catch-up reply arrives, so a live batch can arrive
first and be applied on a stale base. The first T4 runs failed with `RangeError` thrown inside
`prosemirror-collab`'s rebase. Every `steps` message already carries the version after the batch, so the
client now compares it with its own: a batch that is entirely old is ignored, one that leaves a gap triggers
a catch-up request, and an overlap is trimmed. The old client left pending steps in place after a missed gap
and relied on "the next broadcast" to rebase them (a comment in `collab.js`); that is unsafe for the same reason.

**F15. Pre-existing, not fixed: some closes never complete under rapid reconnects.**
In the fuzz, 0 to 3 sockets per run stay in the closing state indefinitely while the server answers other
requests. It happens on `legacy` as well as `verify`, so it is not caused by this work. The server had
accepted the handshake but never reached `add_connection` for that socket. The root cause was not found
(uvicorn 0.54's sans-I/O WebSocket implementation and Starlette are involved; running the harness server
with `COLLAB_TRACE=1` prints the connection lifecycle that shows it). The socket handler also swallowed every exception behind `except Exception: pass`, which
hid a Starlette `WebSocketDisconnected` ("not connected") that the new logging exposed. A half-dead socket is
normal on a phone, and the client reconnects regardless, but the stuck server-side connection should be
understood before this ships.

**F16. The catch-up log is not durable, and version numbering has a structural flaw.**
The step log lives in the authority and starts at the version it loaded, so after a restart or an idle
eviction only newer steps can be served; anything older gets `resync_required`, and the client only warns.
A durable log needs a schema change. `cms_steps` has no `field` column and `draft_version` is one column per
document, while authorities are per (document, field), so two rich-text fields on one document share a
version space **[repo]**; this was not tested. It would be fixed together with the version-collision flaw
ADR 021 left open (a publish generation and a field on each step).

### What this does and does not show

- **Shows:** Path A1 can be made to do what the guide's authority does (apply, validate, serve catch-up) on
  the existing stack; the editor client needed about 60 changed lines, the server about 290 (a 93-line verifier module plus
  changes to the authority, the socket handler and `CMS`), and the AI peer 18 lines in two small fixes. A hardened authority refuses the schema-invalid edit that the Yjs maintainer says a CRDT
  would merge and then delete (T11), and the real-client harness fails exactly where ADR 021 said the
  current design is weak.
- **Does not show:** anything about B or C; behaviour in a real browser; the editor's preview against the
  published Astro rendering; durability under Litestream; attribution to a user; a durable history; or
  scale. The harness's 4 tabs and ~300 operations are a smoke test for convergence, not a load test.
- **What it costs:** a dependency on `prosemirror-py` (single vendor, `lxml`), a Python schema that must be
  kept equal to the editor's, and the durable log and identity work above.

---

## Consequences of proposing (not deciding)

- Nothing changes in production. The editor keeps `prosemirror-collab` with the #34 fix.
- The version-collision bug in ADR 021 stays open until this is decided; it is cheap to fix
  independently if the answer is A, and moot if the answer is Yjs.
- The spike costs a branch and real engineering time (not estimated here). Skipping it risks choosing on architecture taste, which is
  how the current design acquired its unverified claims.
- The trust gaps in F9 and the authorization gap in F7 exist under every option; they could be fixed
  or ticketed without waiting for the decision.

---

## Design History

1. 2026-10-03 — Initial draft, written after the autocorrect duplication bug (#34) showed the server
   cannot detect a corrupted document. Research environment could not reach the Hocuspocus,
   ProseMirror and Yjs documentation sites, hence the evidence labels.
2. 2026-10-03 — Evidence pass. All previously blocked hosts were reachable. Replaced the
   `[verify]`/`[background]` labels with `[checked]`/`[inferred]`/`[unchecked]`. Corrections to the first
   draft: the "Python model from zero" premise (F2); "same client as B" for C (F5); the Yjs "formal
   verification" claim (F5); "per-field scoping carries over" for authorization (F7). New findings: the
   `y-prosemirror` delete-on-invalid behavior (F3), Yjs history trade-offs (F4), the missing
   catch-up and application in our authority versus the guide's (F1). Option A1 restated, tests T11–T13
   added, tie-break order withdrawn pending Joel's weights. Status remains Proposed.
3. 2026-10-03 — Added F10 (Figma as a reference point for Path A) and recorded Joel's stated leaning
   toward Path A. No weights given and no option chosen; status remains Proposed.
4. 2026-10-03 — Ran the Path A1 spike (server-side step application on `prosemirror-py`, catch-up, a
   real-client end-to-end harness) and recorded the results and findings F11–F16. Two AI-peer bugs found
   and fixed on the spike branch. B and C not run. Status remains Proposed.
