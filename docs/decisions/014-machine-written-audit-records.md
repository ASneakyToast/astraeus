# ADR 014 — Machine-written audit records (append-only documents)

**Status:** Accepted  
**Date:** 2026-06-16  
**Informed by:** `docs/use-cases/vpp-rule-governance.md`, `docs/use-cases/vpp-eval-dataset.md`

---

## Context

The existing document lifecycle in starlette-cms is designed for **authored content**: a human
(or supervised agent) drafts a document, it is reviewed, and it is published. The draft/publish
lifecycle exists because the document's meaning is intentional — the author is responsible for
its content and the publish step is an explicit commitment.

A second class of document has emerged from the VPP compliance use cases: **machine-written audit
records**. These are created automatically at the end of a workflow execution — job results,
eval run outcomes, LLM call traces, rules-engine evaluation traces. They share a fundamentally
different set of properties:

- **Created by a machine, not a human.** No author reviews the content before it is persisted.
- **Immutable after creation.** An audit record must not be modifiable — ever. A job that
  auto-denied a submission must remain as written; retroactive edits would destroy the audit trail.
- **No draft state.** The document is authoritative the moment it is written. A "draft" audit
  record has no meaning.
- **High-frequency.** An active pipeline may write hundreds of these per hour. The create+publish
  two-step is friction, and any overhead per write compounds at scale.
- **Cross-referenced to governed config.** The audit record's value comes partly from the typed
  foreign keys it carries to the `DocumentRef` records that were active when it was written —
  the rule config version, the prompt version, the flag catalogue version. Without those refs,
  the record answers "what happened" but not "under what rules."

The current API requires two HTTP calls to create a publishable document: `POST /api/documents`
(creates in draft) then `POST /api/documents/{id}/publish`. For machine-written records, this
is wrong in two ways: the intermediate draft state is meaningless, and the two-step opens a
window where a record exists but is not yet published (a reader could observe a partial state).

There is also no protection against modification. Any document created today can be PATCHed by
any caller with write access. For audit records, a PATCH endpoint should not exist.

The question: should starlette-cms add first-class support for append-only, auto-published
documents, or should machine-written records be handled outside the CMS?

---

## Decision

**Accept `append_only=True` as a first-class modifier on `@block()` and `@cms.block()`.**

`append_only=True` changes the document lifecycle in three ways:

1. **Auto-publish on creation.** `POST /api/documents` with an `append_only` block type creates
   and publishes in a single atomic operation. No separate publish step. The created document is
   immediately in `published` state.

2. **PATCH is rejected.** `PATCH /api/documents/{id}` returns `405 Method Not Allowed` for
   append-only block types. The document body is frozen the moment it is written.

3. **Delete is rejected.** `DELETE /api/documents/{id}` returns `405 Method Not Allowed` for
   append-only block types. Records can be archived (status set to `archived`) by an admin
   operation for data-retention purposes, but the original body is preserved. This also means
   `on_delete="block"` on a `DocumentRef` pointing to an append-only document will always
   succeed — the referenced record cannot be deleted out from under the ref.

`append_only=True` is orthogonal to `singleton=True`. A singleton is always the one published
value of a governed config; an append-only block is a collection of immutable records. They
compose: `singleton=True, append_only=True` is valid but unusual (a singleton you can never
update is just a write-once config).

---

## API shape

```python
# Definition — append-only block type
@cms.block("uw_job_audit", append_only=True)
class UwJobAudit:
    job_id          = TextField(immutable=True, required=True)
    created_at      = TextField(immutable=True, required=True)
    uw_status       = SelectField(choices=["auto_approved", "manual_review", "auto_denied"])
    annual_premium  = NumberField(required=False)
    declared_value  = NumberField(required=False)
    rule_config     = DocumentRef("uw_rules_config", on_delete="block")
    prompt_versions = ListField(item_type=DocumentRef("agent_prompt"))
    evaluations     = JSONField()   # UwDecision.evaluations list — per-flag threshold/actual
    llm_calls       = JSONField()   # token counts, latency, model alias per step
    error           = TextField(required=False)

# Write — single atomic create+publish, no second call needed
await cms.documents.create("uw_job_audit", {
    "job_id":       "job_a1b2c3",
    "created_at":   "2026-06-16T14:23:00Z",
    "uw_status":    "auto_denied",
    "annual_premium": None,
    "declared_value": 78000.0,
    "rule_config":  "doc_thresholds_xyz",   # DocumentRef validated at write
    "prompt_versions": ["doc_prompt_abc"],
    "evaluations":  [...],
    "llm_calls":    [...],
})
# Returns the created+published document in a single response
# Raises DocumentNotFound if any DocumentRef target does not exist
# No /publish call required or accepted

# Read — same as any document
records = await cms.documents.list("uw_job_audit",
    filters={"rule_config": "doc_thresholds_xyz"},
    order_by="created_at",
    order="desc",
    limit=50,
)

# PATCH attempt — rejected at framework level
await cms.documents.patch("uw_job_audit", "doc_abc123", {"uw_status": "auto_approved"})
# Raises ImmutableDocumentError (405 Method Not Allowed on the HTTP API)
```

---

## The compliance use case this enables

The VPP underwriting pipeline must be able to answer, for any historical job:

- What UW decision was reached, and what per-flag threshold/actual values drove it?
- What rule configuration (thresholds, premium rates) was active at decision time?
- What prompt versions were used by the fraud synthesiser and report writer agents?

With `append_only=True` and `DocumentRef`:

```python
# Compliance query: all jobs denied under rule config version doc_thresholds_xyz
records = await cms.documents.list("uw_job_audit",
    filters={"uw_status": "auto_denied", "rule_config": "doc_thresholds_xyz"},
    resolve_refs=["rule_config"],
)

for r in records:
    config = r.rule_config  # already resolved via resolve_refs
    print(f"Job {r.data['job_id']}: denied at confidence {r.data['evaluations'][...]}")
    print(f"  Rule config published: {config.data['published_at']}")
    print(f"  Fraud deny threshold: {config.data['fraud_critical_deny_confidence']}")
```

This query is impossible without the `DocumentRef` link. Storing the rule config doc ID as a
plain string field would require a second lookup, and without `on_delete="block"`, the referenced
config document could have been deleted or archived, making the historical record incomplete.

---

## What this does NOT solve

**LLM call tracing at the token level.** The `llm_calls` field is a `JSONField` — it stores
whatever the application layer puts there. starlette-cms has no concept of LLM clients, token
counts, or model resolution. The application is responsible for capturing per-call metadata
(model alias, token counts, latency, whether the call succeeded) and writing it into this field.
The framework provides durable, immutable, queryable storage; the instrumentation is out of scope.

**Resolved model IDs from the LiteLLM proxy.** If `riky-vibe` is a proxy alias, starlette-cms
cannot resolve it to a concrete model version. This requires a change at the proxy or SDK layer.
The `llm_calls` field should store both the alias (`riky-vibe`) and the resolved ID when
available; the application layer is responsible for obtaining the resolved ID.

**High-frequency write performance at production scale.** The current persistence layer uses
Piccolo ORM with schema validation on every write. For hundreds of records per hour this is
acceptable. At thousands per hour, raw `INSERT` statements would be faster. This is noted as a
known tradeoff, deferred until actual load data exists.

---

## Rejected alternatives

**1. Machine-written records outside Astraeus (plain SQLite table):**
The application maintains a separate `job_audit` table with string fields storing Astraeus
document IDs. Cross-queries require joining across two stores. `on_delete="block"` semantics
must be enforced by application code. Rejected for the primary use case because: the referential
integrity guarantee is the core compliance value — without it, the question "which rule config
was active for this job" cannot be answered with certainty if a config document is later deleted
or modified.

**2. Use existing document lifecycle, enforce immutability by convention:**
Document PATCH is restricted at the API-key permission level. Rejected because: permission
boundaries are an operational concern, not a structural one — a future permissions change or
an administrative mistake could silently corrupt the audit trail. Immutability needs to be
structurally enforced, not permission-enforced.

**3. Separate `audit` API alongside `documents`:**
A dedicated `cms.audit.write(block_type, data)` / `cms.audit.query(...)` surface. Rejected
because: it duplicates the document storage, filtering, pagination, and `DocumentRef` resolution
infrastructure that already exists and works. The append-only constraint is a narrow behavioral
change; it does not justify a parallel storage subsystem.

**4. Event sourcing / append-only log (Kafka, Kinesis, append-only file):**
For pure event streams where you need replay semantics and ordered partitions, an event log is
the right abstraction. Rejected for this use case because: the compliance query pattern
(filter by rule_config, filter by uw_status, resolve refs to governed config) is a relational
query pattern, not a replay pattern. `DocumentRef` referential integrity requires a database,
not a log. The VPP audit records are records, not events.

---

## Interaction with existing ADRs

**ADR 009 (Singleton documents):** `append_only=True` and `singleton=True` are orthogonal. The
governed config documents that `append_only` audit records reference are singletons (one
authoritative published value at a time). The audit records are the collection that observes and
references those singletons.

**ADR 010 (DocumentRef):** `append_only=True` is most valuable in combination with `DocumentRef`.
An append-only document without refs is just an immutable blob — useful, but not the compliance
use case. The two features compose: `DocumentRef` on an `append_only` block type gains an
additional invariant — the ref cannot become a dangling pointer via a retroactive delete of the
audit record (since the audit record itself cannot be deleted), and `on_delete="block"` on the
target means the referenced config version cannot be deleted while audit records point to it.

---

## Consequences

**Positive:**
- Machine-written audit records become a first-class concept with structural, not
  convention-enforced, immutability
- The create+publish two-step is eliminated for the high-frequency write path
- `DocumentRef` referential integrity extends naturally to audit records — governed config
  versions cannot be destroyed while job records reference them
- Compliance queries across job records and their governing config versions are single CMS
  API calls with `resolve_refs`

**Negative / tradeoffs:**
- `append_only=True` is a new modifier the block registry must understand
- Admin UI must clearly distinguish append-only collections (no edit button, no delete button)
  from regular document collections — a starlette-editor concern, deferred to editor Phase 2
- The single-step create+publish changes the document lifecycle state machine — the persistence
  layer must handle the atomic create+publish as a transaction

**Neutral / deferred:**
- Whether append-only documents can be hard-deleted by a superadmin for legal data-retention
  (right-to-erasure) is deferred. The initial implementation supports `archived` status for
  soft-deletion that preserves the record structure while removing it from normal queries.
- Bulk write API (`POST /api/documents/batch` for append-only types) is deferred until
  throughput requirements justify it.

---

## Implementation notes

- `BlockRegistration` gains `append_only: bool = False`
- On `POST /api/documents` with an `append_only` block type: create the document and immediately
  call `publish()` within a single DB transaction; return the published document body
- On `PATCH /api/documents/{id}` or `DELETE /api/documents/{id}` with an `append_only` block:
  return `405 Method Not Allowed` with body `{"error": "append_only documents cannot be modified"}`
- The `published` column is always `True` for append-only documents; `singleton_status` is always
  `None` (append-only is a collection, not a singleton)
- Webhook payload for append-only document creation uses event type `document.created` with
  `"append_only": true` in the payload — no `document.published` event is fired separately
  since creation and publication are atomic
