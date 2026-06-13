# ADR 010 — Document references (typed foreign keys between documents)

**Status:** Proposed  
**Date:** 2026-06-13  
**Informed by:** `docs/use-cases/vpp-eval-dataset.md`

---

## Context

starlette-cms documents are currently standalone. There is no mechanism to express a typed
relationship between documents — for example, an eval entry that references a submission, or a
test scenario that references the rule config version it was written for.

These relationships emerge naturally in the USAA VPP use cases:

- `EvalEntry.submission_ref` → a `jewelry_item` document
- `EvalEntry.rule_config_ref` → a `global_thresholds` singleton document
- `EvalEntry.prompt_refs` → a list of `uw_prompt` singleton documents
- `TestScenario.rule_config_ref` → the `global_thresholds` version active when the scenario
  was authored

Without first-class reference support, the application layer must manage these relationships
manually — storing document IDs as plain string fields, resolving them with separate API calls,
and enforcing referential integrity by convention. This is fragile, invisible to the framework,
and unsupported by the admin UI.

The question: should starlette-cms introduce a `DocumentRef` field type as a first-class
primitive, or should cross-document relationships remain an application-layer concern?

---

## Decision

**Accept `DocumentRef(block_type)` as a first-class field type.**

`DocumentRef` is a typed foreign key that:

1. **Stores** a document ID (UUID string) in the referencing document's data
2. **Validates** at write time that the target document exists and has the declared block type
3. **Resolves** lazily — calling `.resolve()` on a ref fetches the target document
4. **Supports bulk resolution** — `documents.list(..., resolve_refs=True)` avoids N+1 queries
5. **Enforces configurable integrity** on delete of the target document (see below)

---

## API shape

```python
# Field definition
@cms.block("eval_entry")
class EvalEntry:
    submission_ref:  DocumentRef(block_type="jewelry_item",        label="Submission")
    rule_config_ref: DocumentRef(block_type="global_thresholds",   label="Rule Config Version",
                                  on_delete="nullify")
    prompt_refs:     ListField(item_type=DocumentRef(block_type="uw_prompt"), label="Active Prompts")

# Write — ref stored as document ID
await cms.documents.create("eval_entry", {
    "submission_ref":  "doc_01j...",
    "rule_config_ref": "doc_02k...",
    "prompt_refs":     ["doc_03a...", "doc_04b..."],
    # ... other fields
})
# Raises DocumentNotFound if any referenced document ID does not exist
# Raises BlockTypeMismatch if a referenced document is not of the declared block_type

# Read — lazy resolution
entry = await cms.documents.get("doc_05x...")
submission = await entry.submission_ref.resolve()   # second API call
print(submission.data["declared_value"])

# Bulk resolution — single query per ref type
entries = await cms.documents.list("eval_entry", resolve_refs=["submission_ref"])
for entry in entries:
    print(entry.submission_ref.data["declared_value"])  # already resolved, no extra calls
```

---

## Reference integrity on delete

When a referenced document is deleted, three behaviors are configurable via `on_delete`:

| `on_delete` value | Behavior |
|---|---|
| `"block"` (default) | Refuse to delete the target if any document references it. Raises `ReferencedDocumentError`. |
| `"nullify"` | Set the ref field to `None` in all referencing documents. The referencing document remains valid. |
| `"cascade"` | Delete all documents that reference the target. Use with caution. |

`"block"` is the default because it makes orphaned references impossible — the safest option
for audit trail integrity. `"nullify"` is appropriate for soft-governance refs (e.g., a rule
config version is archived but eval entries should remain). `"cascade"` is available but
intentionally awkward to invoke (requires explicit opt-in).

---

## What DocumentRef does NOT do

- **No lazy loading of entire graphs** — `resolve()` fetches one document; traversing a graph
  requires explicit calls. Astraeus is not an ORM.
- **No circular reference detection at definition time** — circular refs are valid (A refs B
  refs A) but will raise `MaxDepthExceeded` if resolved recursively without a depth limit.
- **No cross-version pinning** — a `DocumentRef` stores a document ID, not a document ID +
  version. It always resolves to the current state of the referenced document. For point-in-time
  snapshots (e.g. "which rule config version was active at eval time"), store the version number
  as a separate `NumberField` alongside the ref. This is intentional: the ref is a pointer to
  the governed artifact; version pinning is a separate concern.

---

## Rejected alternatives

**1. Plain string fields storing document IDs:**
Applications currently do this. Rejected because: no validation at write time (silent orphans),
no framework support for resolution (manual API calls), no admin UI awareness (IDs displayed
as raw strings, not resolved names), no integrity semantics on delete.

**2. Embedded documents (nested block data inline):**
Instead of a ref, store a snapshot of the referenced document's data inline. Rejected because:
duplication across documents diverges on update, there is no "current state" for a referenced
config, and snapshot semantics are better handled by the application layer when actually needed
(e.g. EvalEntry already stores a snapshot of the workflow output separately from the ref).

**3. Full relational model (JOIN-capable queries):**
A proper relational layer with JOIN support across document types. Rejected for now because:
over-engineered for the current use cases, requires significant changes to the persistence
layer, and the `resolve_refs=True` bulk fetch covers the common case without JOIN semantics.
Revisit if query patterns demand it.

---

## Consequences

**Positive:**
- Cross-document relationships are expressed in the schema, visible to the admin UI, and
  enforced by the framework rather than by convention
- The eval dataset attribution use case (which prompt version caused this score drop?) becomes
  answerable without manual ID lookups
- `resolve_refs=True` prevents the N+1 query problem in list views

**Negative / tradeoffs:**
- Write validation (checking that referenced documents exist) adds latency to document creation
- `on_delete="block"` means admin UI delete flows must surface reference counts to the user
  ("this document is referenced by 47 eval entries — delete anyway?")
- `DocumentRef` in `ListField` (e.g. `prompt_refs`) requires the persistence layer to handle
  arrays of IDs, which is a non-trivial extension to the document data model

**Neutral / deferred:**
- The admin UI rendering of `DocumentRef` (show resolved document name + link instead of raw ID)
  is a starlette-editor concern, deferred to editor Phase 2
- Cross-version pinning (storing a version number alongside the ref) is documented as an
  application pattern, not a framework feature, until a clear use case demands it

---

## Implementation notes

- `DocumentRef` is a `_BaseField` subclass; it stores a `str` (UUID) in the document data
- The Pydantic model generated from a block containing `DocumentRef` treats the field as
  `str | None` — resolution is a framework concern, not a Pydantic concern
- Validation on write calls `cms.documents.exists(id, block_type=declared_block_type)` —
  one DB query per ref field per write; acceptable for the current use case scale
- `resolve()` is an `async` method on a `DocumentRefProxy` object returned when reading
  a document with ref fields
- `documents.list(..., resolve_refs=["field_name"])` issues one `IN (ids...)` query per
  resolved ref field — O(1) queries regardless of list size
