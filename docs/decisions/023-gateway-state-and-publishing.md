# ADR 023 — Gateway state, retries and publishing

**Status:** Accepted. Supersedes parts of [ADR 015](015-starlette-cms-gateways.md) — see *What this supersedes*.
**Date:** 2026-10-02

---

## Context

joellithgow.com syncs iNaturalist outings and Spotify months through `starlette-cms-gateways`. Running it
for real showed that ADR 015's treatment of incremental sync, state and publishing does not hold:

1. **Every run parked a draft on live documents.** The body hash covered the whole body, so any upstream
   change counted as an update. `PATCH` on a published document never edits the live body: it writes
   `draft_body`. And `upsert` published only after creating, never after updating. Net effect: 25 published
   posts showed "Edited since publishing" though nobody edited them.
2. **ADR 015's incremental-sync example is wrong.** It uses `JobStore.get_last_synced()` as the cursor. That
   is `finished_at` of the last job with status `done`, and a job is `done` even when items failed, so a run
   that dropped items still moved the "cursor" past them. ADR 015 also says incremental sync needs "no
   boilerplate in the subclass". It never did: every gateway had to compute its own window.
3. **The cursor was not durable and not single.** `JobStore` wrote `gateway_jobs.db` into the working
   directory. The admin page (in the CMS pod) and the MCP sidecar (another pod) each had their own file, so
   there were two cursors, and both were lost on a restart.
4. **A stuck document froze the cursor.** The first rework only advanced the cursor after a *clean* run
   (nothing deferred, nothing failed). One post with a person's draft on it meant no run ever advanced, and
   every `since_last_sync` re-read everything.
5. **Publishing a run as one changeset strands a run.** An update was published by publishing the run's
   changeset at the end. A failure part-way left documents PATCHed and unpublished, and the next run
   deferred them as if a person had drafted them.

## What this supersedes

Of ADR 015: the *Incremental sync* paragraph and its example under **API shape**; the rationale
**Cursor management is the gateway's own responsibility** and the `JobStore` rationale that says it is
optional operational state in a separate file; the Consequences bullet on incremental sync needing no
boilerplate; and Design History item 4 (examples that read `get_last_synced()`). ADR 015's remaining decisions
stand: `import_ref` as the dedup key, the worker as an external HTTP client of the CMS, `auto_publish`
defaulting to `False`, and **no `since` injected into `fetch()`**.

## Decision

### 1. Sync state lives in the CMS's own database, behind the gateway API

Three things outlive a run: the **cursor**, the **retry list** and the **job history**. They are tables
(`gateway_cursors`, `gateway_retry`, `gateway_sync_jobs`) in the CMS's database file, the one file that is
persistent and replicated (Litestream replicates the whole file, so new tables ride along). `GatewayAdmin`
defaults its `JobStore` to that file when the CMS is on SQLite, and warns when it is not.

Only the CMS process opens the file. A worker that is not the CMS (the `gateways` CLI, an MCP sidecar in
another pod) reads and writes the state through the CMS gateway API: `GET/PUT /api/gateways/{name}/cursor`,
`GET/PUT .../retry`, `POST .../runs` and `PATCH .../runs/{run_id}`, authenticated like the other writes.
`RemoteSyncState` is the client; `JobStore` and `RemoteSyncState` both satisfy the `SyncState` protocol that
`BaseGateway` takes. So there is **one cursor however a run starts**, it survives a restart, and every entry
point records its run (`run_recorded`), which makes "last synced" true.

Every connection sets WAL and a busy timeout, so the state's writes and the CMS's wait for each other.

### 2. The cursor never freezes; what a run could not finish goes on a retry list

After any run that did not raise, the cursor is set to **the run's start time**. A run that raises changes
neither the cursor nor the retry list. A `custom` backfill never moves it. A gateway that does not call
`resolve_window()` (a page-token gateway) has no cursor, as before.

An item a run could not finish goes on the gateway's **retry list** instead of holding the cursor back:
*deferred* (a person's draft or unpublish is in the way) or *error* (the write failed). An optional hook,
`BaseGateway.refetch(import_refs)`, rebuilds items for specific refs; the framework calls it at the start of
the next run, whatever its range. A gateway refetches the smallest unit that can rebuild an item (an
iNaturalist outing's day, a Spotify month). A ref the hook yields nothing for is dropped (the source no
longer has it). A gateway without the hook only *reports* its list; entries clear when a later run happens to
process them. A retry-list entry keeps the time it first went on the list.

A fixed lookback window was considered and rejected: syncs here are manual and irregular.

### 3. Ownership, and whose draft it is

Unchanged from the first rework, and part of the contract: a gateway declares `owned_fields`; only those are
hashed and written on update; a re-sync that finds nothing new writes nothing.

New: **drafts are checked before the hash**, and a draft is classified by what it changes
(`starlette_cms_gateways.drafts.draft_verdict`). A draft that differs from the live body only in owned fields
is the gateway's own leftover (a `PATCH` whose publish failed, or a revision awaiting review): the gateway
re-PATCHes it and publishes (a review gateway only re-PATCHes). A draft that touches anything else, a staged
unpublish, or a document a person unpublished, is a person's: deferred if the source changed, skipped if not
(there is nothing to write and nothing to wait for). A gateway that declares no `owned_fields` cannot tell
whose draft it is and defers on any. This is what lets a review gateway (`auto_publish = False`) take a
second and third update to a never-published draft, and what finishes a document whose publish failed.

### 4. Each document is published as soon as it is written

On an `auto_publish` gateway, the document is published right after its create or update succeeds. There is
no end-of-run changeset publish: a failure strands one document, and the next run finishes it. A gateway that
does not publish groups its writes in one lazily created review changeset, as before.

**Core change (starlette-cms).** The `PATCH /api/documents/{id}` handler links the document into an open
changeset and creates a date-titled one ("Oct 2", "Oct 2 (2)", …) when there is none. Publishing one document
at a time therefore left one open changeset per updated document in the editor (reproduced in
`test_changesets.py` before the fix). The smallest fix is an opt-out: `PATCH` honours
`X-Skip-Changeset: 1`, and `CMSClient.update_document(link_changeset=False)` sends it. An explicit
`X-Active-Changeset-Id` still wins.

Rejected: unlinking a document from its open changesets when it is published through the single-document
endpoint. It would match what changeset publish already does, but it changes the editor's behaviour for
every caller and still leaves each auto-created changeset behind, empty.

### 5. Ranges (unchanged)

`since_last_sync`, `all_time` and `custom`, with `SyncRange`, `resolve_window()` and `cursor_overlap`, as
introduced with the first rework. Deletions are never made by a sync.

## Consequences

**Positive**
- One cursor, durable, and the same for the admin page, the CLI and MCP tools.
- A stuck document no longer slows every run; it is listed, retried, and cleared when a person acts.
- A failed publish or a failed write costs one document one run.

**Negative / trade-offs**
- Workers need the CMS API to run at all (no offline CLI run), and CMS and sidecar must be on compatible
  versions (they ship in one image in joellithgow).
- The default state file assumes the CMS is on SQLite. Elsewhere the integrator must pass `jobs_db_path`.
- `X-Skip-Changeset` is now part of the CMS's public write API.
- A retry-list entry for a gateway with no `refetch` hook is only cleared by a run that covers the item.

**Testing.** Anything touching draft, publish, changeset or state semantics is tested against the real
in-process CMS over `ASGITransport` (`test_sync_state.py`, `test_sync_ownership.py`), not against mocked HTTP.
