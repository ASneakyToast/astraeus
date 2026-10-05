# ADR 025 — A default changeset for new drafts

**Status:** Accepted. Supersedes nothing: it adds to how documents join changesets (ADR 018 §4) and leaves
[ADR 023](023-gateway-state-and-publishing.md)'s one-changeset-per-gateway-run untouched.
**Date:** 2026-10-05

---

## Context

A changeset is the unit of publish, but what put a document in one was accidental:

- **`POST /api/documents` linked nothing.** A draft made through the API or the MCP tools (the content
  bot, a Claude session) was in no changeset until somebody edited it.
- **`PATCH` made one per document.** An edit that named no changeset and touched a document in none created a
  date-titled changeset ("Oct 4") for that one document, so two posts written in a sitting landed in
  "Oct 4" and "Oct 4 (2)". The browser editor hides this, since it adopts the first changeset and keeps
  adding to it. A bot does not.
- **Publishing one document left it in its changeset**, still listed as pending, and published again with the
  rest.

The result is that "what is waiting to go live" has no single answer, and the changeset panel's *orphaned
drafts* section is where the rest has to be found. The owner of joellithgow.com works the other way round:
a Claude session writes a few posts, then on a phone they open the site, look at them and publish. That needs
one place the new posts are, and one thing for Publish to ship.

## Decision

### 1. A configured default changeset

`CMS(default_changeset="Staging")` names a changeset new drafts collect in. Unset (the default), nothing here
changes.

- **Create** links the new document to the open changeset with that title, making one if none is open.
- **An edit that names no changeset**, and whose document is in no open changeset, joins it too. This covers
  `PATCH`, the staged publish/delete endpoints, and the collab socket, which now share one helper
  (`link_document_to_changeset`). A stale changeset id (one already published or deleted) falls back to it.
- A document already in an open changeset stays there. A request that **names** a changeset (a gateway run,
  the browser editor's active changeset) is honoured and never touches the default.
- Append-only documents, which are born published, and chat documents are not linked.

"Open changeset with that title" is looked up, not remembered. Publishing it ends it, and the next draft
starts a fresh one. A lock makes concurrent creates agree on one.

### 2. Publishing a document on its own takes it out of open changesets

It is live, so it has no change left to carry. This matches what changeset publish already does to a
document's *other* changesets. Published and reverted changesets keep their history.

### 3. The editor's Publish ships the default when nothing else is chosen

`GET /api/changesets/default` returns the open default changeset with its documents, or `null`. It never
creates one. The inline editor's Publish targets the changeset the browser is working in, else that one, and
the confirm names it and its size ("Publish “Staging” (3 documents)?"). A browser that has picked nothing,
a phone for instance, previously published a single document from the page.

### 4. What is not decided here

- **Staging is a bag, not a review queue.** Publishing it publishes everything in it. A draft not ready goes
  in another changeset (the panel moves documents) or stays out of it.
- **Existing orphans are not moved by the CMS.** An application that adopts this has drafts in no changeset.
  Moving them is a one-off the application owns (joellithgow: `cms/stage_orphan_drafts.py`, dry-run by default).
- **Gateways keep their own.** A run still opens one changeset, publishes it once, and is not affected.
  Rejected: routing gateway writes through the default, which would publish a sync together with
  whatever else is staged.

## Consequences

**Positive**
- One answer to "what is waiting": the default changeset. Two posts written in one sitting are together.
- Publish on a device with no history does the obvious thing.
- No new table or column; the default is a title, found by query.

**Negative / trade-offs**
- Everything in the default ships together, including a half-written post someone forgot. The confirm shows the
  count, not the titles.
- The default is matched by **title**. Renaming the open changeset in the editor makes the next draft start a
  new one; a second changeset with the same title is allowed and the oldest wins.
- A document published through `POST /api/documents/{id}/publish` now leaves its changesets; a caller that
  relied on it staying listed will see it gone.
- **The panel's "Review & Publish" diff shows nothing for a document made of fields.** It extracts text only
  where the whole body *is* a ProseMirror document (`_extract_text` in `api/changesets.py`); a blog post's rich
  text sits inside one field, so an edited post reads "No changes" and only "new" is labelled. Not changed by
  this ADR, and not fixed here, but it is the screen a reviewer looks at before publishing a changeset that now
  gathers more drafts.

**Testing.** Against the real in-process CMS (`tests/test_default_changeset.py`): create, edit, stale id, named
changeset wins, concurrent creates, fresh default after publish, single-document publish, the endpoint.
