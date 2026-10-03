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

---

## Assessment

Ratings are my reading of the evidence, not measurements. Cells with **?** are what the spike must
settle; they are not weaknesses of the option. "F#" points at the finding the cell rests on.

| Criterion | A1 Authority in Python (`prosemirror-py`) | A2 Node authority | B Hocuspocus | C pycrdt (Python) |
|---|---|---|---|---|
| 1 Convergence | Good: central order. Rejects and rebase churn under bursts | Good, same | Strong at the Yjs level. At the ProseMirror level, merged state can violate the schema and the binding then deletes content (F3) | Same engine, same caveat (F3) |
| 2 Server holds truth | Strong once built: steps are applied and checked (F1) | Strong: same code as client | **Weaker than the draft said.** Server holds a merged Yjs state; nothing checks it is a valid PM document unless added (F3) | Same, and a validator would be `prosemirror-py` (F2), so C needs it too |
| 3 Attribution | Per-step ID is stored. Today client-asserted; can be bound to the authenticated user (F7) | Same | **?** Per update via `onChange` context; `onStoreDocument` sees only state, debounced 2 s/10 s (F5). Per-character authorship is not native | **?** Per update at write; squashing discards it (F6) |
| 4 History | Log can become verified. Fix version-collision bug first | Same | **Weakened.** Snapshots need `gc:false` everywhere, which one large team abandoned; undo manager blocks GC (F4) | Same (F4); `pycrdt-store` squashes (F6) |
| 5 AI peer | Unchanged (could use a real `Transform`) | Unchanged | Needs a Yjs write path: `openDirectConnection`, broadcast behavior **[unchecked]** (F5) | **?** XML insert/format API exists (F6); result must render in the binding |
| 6 Missed updates | Weak today; fixed by adding `stepsSince` (F1) over a log with the collision bug | Same | Strong: state-vector sync is built in | Strong |
| 7 Persistence | Strong: existing tables | Strong | Moderate: binary state is truth, JSON one-way and must not be re-hydrated (F5) | Moderate: store must write into `content.db`; default is a second SQLite file (F6) |
| 8 Package independence | Strong: pure Python, plus one small dependency (F2) | Weak: Node runtime | Weak: Node runtime | Python server; needs `prosemirror-py` for validation (F2) and a hand-written JSON reader/writer (F6), tight `pycrdt` pin |
| 9 Maturity / lock-in | `prosemirror-collab` is small and canonical (F1). `prosemirror-py`: one vendor, 63 stars, 11-month gap between 0.5.2 and 0.6.0 (F2) | Strong engine, bespoke glue | Yjs very mature; Hocuspocus smaller and **provider lock-in confirmed**; one project left it (F5) | Yjs mature; `pycrdt` Beta, `pycrdt-websocket` 0.x with a tight pin (F6) |
| 10 Migration cost | **Low to moderate**: editor and chat unchanged; add authority + Python schema (F2, F8) | Moderate | **High**: editor, history, chat write path, stored docs, tests (F8) | **High**, no Node, plus JSON converter |
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

No option is chosen here. Run a time-boxed spike on **B and C** (the Yjs candidates) against a hardened
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

**Still to read before the spike (everything else on the original list is done):**

- Whether a stock JS `y-websocket` client interoperates with `pycrdt-websocket`, and how to mount its
  ASGI server and lifespan beside the CMS app (F6).
- Whether Hocuspocus `openDirectConnection().transact` broadcasts to clients and triggers
  `onStoreDocument` (F5).
- Whether any Yjs release since April 2025 changed the UndoManager/GC behavior in #3797 (F4), and whether
  `y-prosemirror` has changed the delete-on-invalid behavior (F3).
- Whether `prosemirror-py` 0.6.1 is current against `prosemirror-model` / `prosemirror-transform` latest (F2).
- Source of the XWiki problems beyond their post (F5): the thread names symptoms, not causes.

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
