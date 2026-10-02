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
5. **A failed run left drafts the next run took for a person's.** The first rework published the run's
   changeset in a `finally`, behind flags that made some items skip it. When a publish failed, the documents it
   left PATCHed and unpublished were then deferred forever as if a person had drafted them. The fault was
   the draft classification, not the batching (decision 3).

## What this supersedes

Of ADR 015: the *Incremental sync* paragraph and its example under **API shape**; the rationale
**Cursor management is the gateway's own responsibility** and the `JobStore` rationale that says it is
optional operational state in a separate file; the Consequences bullet on incremental sync needing no
boilerplate; and Design History item 4 (examples that read `get_last_synced()`). ADR 015's remaining decisions
stand: `import_ref` as the dedup key, the worker as an external HTTP client of the CMS, `auto_publish`
defaulting to `False`, and **no `since` injected into `fetch()`**.

## Decision

### 1. Sync state lives in the CMS's own database, behind the gateway API

Two things outlive a run: the **cursor** and the **job history**. They are tables
(`gateway_cursors`, `gateway_sync_jobs`) in the CMS's database file, the one file that is
persistent and replicated (Litestream replicates the whole file, so new tables ride along). `GatewayAdmin`
defaults its `JobStore` to that file when the CMS is on SQLite, and warns when it is not.

Only the CMS process opens the file. A worker that is not the CMS (the `gateways` CLI, an MCP sidecar in
another pod) reads and writes the state through the CMS gateway API: `GET/PUT /api/gateways/{name}/cursor`,
`POST .../runs` and `PATCH .../runs/{run_id}`, authenticated like the other writes.
`RemoteSyncState` is the client; `JobStore` and `RemoteSyncState` both satisfy the `SyncState` protocol that
`BaseGateway` takes. So there is **one cursor however a run starts**, it survives a restart, and every entry
point records its run (`run_recorded`), which makes "last synced" true.

Every connection sets WAL and a busy timeout, so the state's writes and the CMS's wait for each other.

### 2. The cursor never freezes; what a run could not finish is reported, not remembered

After any run that did not raise, the cursor is set to **the run's start time**, whatever the run deferred
(a person's draft or unpublish is in the way) or failed on. A run that raises changes nothing. A `custom`
backfill never moves it. A gateway that does not call `resolve_window()` has no cursor, as before.

Deferred and failed items are listed in the run's result (and in the MCP reply and CLI output), and that is all.
There is no retry list and no re-fetch hook: an incremental run meets such a document again only if its source
changes, and an `all_time` (or `custom`) run catches it up. That is the same rerun/backfill a person already
does to repair or extend content, so it is not given machinery of its own.

Rejected: a persisted per-gateway retry list with an optional `refetch(import_refs)` hook (built, then removed
before merge as more than the problem needed); a fixed lookback window (syncs here are manual and irregular);
freezing the cursor on the first deferred item (one stuck post makes every run re-read everything).

`JobStore.get_last_synced()` stays, for the admin page's "Last synced" label only. It is when a run
*finished* and a run is `done` even when items failed, so it is never a cursor.

### 3. Ownership, and whose draft it is

Unchanged from the first rework, and part of the contract: a gateway declares `owned_fields`; only those are
hashed and written on update; a re-sync that finds nothing new writes nothing.

New: **drafts are checked before the hash**, and a draft is classified by what it changes
(`starlette_cms_gateways.drafts.draft_verdict`). A draft that differs from the live body only in owned fields
is the gateway's own leftover (a `PATCH` whose publish failed, or a revision awaiting review): the gateway
re-PATCHes it and publishes (a review gateway only re-PATCHes). A draft that touches anything else, a staged
unpublish, or a document a person unpublished, is a person's: left alone and reported as deferred if the source changed, skipped if not
(there is nothing to write and nothing to wait for). A gateway that declares no `owned_fields` cannot tell
whose draft it is and defers on any. This is what lets a review gateway (`auto_publish = False`) take a
second and third update to a never-published draft, and what finishes a document whose publish failed.

### 4. A run is one changeset, published once

Every write of a run goes into a changeset opened lazily on the first write, so a quiet run opens none. What is
headed for publication (everything on an `auto_publish` gateway, bar an item with `published=False`) goes into one
new changeset for the run, which the gateway publishes **once, at the end**: one publish, so one
`changeset.published` webhook (one site build for a sync of any size), and all or nothing, so the site never
shows half a sync. What is held for review (everything on a gateway with `auto_publish = False`, or an item with
`published=False`) goes into a separate open review changeset and is never published by the gateway.

A failure is loud and recoverable:

- If the publish raises, the run raises: the job is recorded as an error, and **the cursor is not advanced**.
  The next run covers the same items, finds the documents' leftover drafts (the gateway's own, decision 3),
  re-writes them into a new changeset and publishes that, which also removes them from the old changeset. The
  empty changesets a failed run leaves behind (named for this gateway's runs, empty, open) are deleted at the
  end of a successful publish, and only those.
- A document that cannot be written (the CMS validates every write) is an item error: it is left out of the
  changeset and the rest publish.
- A document created by a run that never published it is linked into the next run's changeset.

The cursor therefore moves only after the publish succeeds, whatever was deferred or failed on.

Rejected: **publishing each document right after its write.** Built, then reverted. It fixes nothing the
changeset does not, and it costs: one `document.published` webhook per document (a build-hook consumer gets up to N
builds for a sync of N documents, and the CMS does not coalesce deliveries); a half-published run when something
fails part-way; and a core change, because the `PATCH` handler links every edit into an open changeset and creates a
date-titled one when there is none, which per-document publishing left behind once per document. A run
changeset never meets that, since every PATCH names the changeset. Also rejected: a debounce on the webhook, which
treats a symptom of that choice.

Known trade-off: a changeset publishes everything in it, so a person who edits a document the run has already
written, in the seconds before the run's publish, would have that edit published too. The window is the length of
one run.

### 5. Ranges (unchanged)

`since_last_sync`, `all_time` and `custom`, with `SyncRange`, `resolve_window()` and `cursor_overlap`, as
introduced with the first rework. Deletions are never made by a sync.

## Consequences

**Positive**
- One cursor, durable, and the same for the admin page, the CLI and MCP tools.
- A stuck document no longer slows every run; it is listed in the result, and caught up by the next `all_time`.
- A sync is one publish and one site build, however many documents it changes, and it is all or nothing.
- A failed publish is loud (the run raises, the job is an error) and self-healing (the cursor stays, the next run
  finishes the documents and cleans up).

**Negative / trade-offs**
- Workers need the CMS API to run at all (no offline CLI run), and CMS and sidecar must be on compatible
  versions (they ship in one image in joellithgow).
- The default state file assumes the CMS is on SQLite. Elsewhere the integrator must pass `jobs_db_path`.
- Documents are not live until the end of the run, and a failed publish leaves them unpublished until the next
  run succeeds.
- An item left alone or failed in one run is not retried by later incremental runs unless its source changes; someone has to run `all_time`.

**Testing.** Anything touching draft, publish, changeset or state semantics is tested against the real
in-process CMS over `ASGITransport` (`test_sync_state.py`, `test_sync_ownership.py`), not against mocked HTTP.
