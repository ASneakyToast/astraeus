# ADR 016 — Absent vs null field semantics in document bodies

**Status:** Accepted  
**Date:** 2026-06-19  
**Informed by:** real-world integration with Astro Content Layer; LLM-authored document workflows

---

## Context

When a document is stored in starlette-cms and an optional field has no value, the Pydantic
model serializes it as `null` in the stored JSON body. This happens because `model_builder.py`
maps optional fields to `str | None` with `default=None`, and `model_dump()` includes all
fields regardless of whether they were explicitly set.

The result is that the API response for a document with several unfilled optional fields looks
like:

```json
{
  "slug": "my-post",
  "title": "My Post",
  "description": null,
  "author": null,
  "end_date": null,
  "location": null
}
```

This collapses two semantically distinct states into one:

1. **Never set** — the field was not addressed when the document was created or last updated.
   The LLM didn't fill it in, or the field didn't apply, or it was added to the schema after
   the document was created.

2. **Explicitly cleared** — the field previously had a value and was deliberately set to `null`
   by a human or an agent. "This project has no live link." "This role has no end date."

Consumers — whether Astro loaders, LLM agents reading content for context, or downstream
services — cannot distinguish between these two states from the API response alone. This causes
two practical problems:

**Problem 1: Schema validation noise in consumers.** Astro's Zod schemas use `.optional()` to
handle absent fields, but `.optional()` does not accept `null` — those are distinct in
TypeScript. When the CMS returns `"description": null`, Zod rejects the document at build time
unless the consumer schema is widened to `.nullable().optional()`. This is defensive code
written to work around a CMS serialization behavior, not a real constraint of the data.

**Problem 2: LLM agents cannot infer intent.** When an LLM fills out a document and sends back
`"end_date": null`, it is ambiguous: does `null` mean "this is a current role with no end date"
(intentional), or "I did not provide an end date" (not addressed)? If both states serialize
identically, an agent reading the document back has no signal about prior intent. This degrades
the quality of downstream LLM workflows that use CMS content as context.

The industry consensus (Contentful, Sanity.io, DRF, Wagtail) is that optional fields with no
value should be **absent from the serialized output**, not present as `null`. `null` is reserved
for **explicit writes** — a caller that deliberately passes `"field": null` to clear a value.

---

## Decision

**Optional fields that have not been explicitly set are omitted from the document body in
storage and in API responses. `null` in the API response means "this field was explicitly set
to null by a caller."**

This is implemented via two changes:

### 1. `model_dump(exclude_none=True)` at all write sites

In `api/documents.py`, every call to `validated.model_dump()` before persisting to the database
is changed to `validated.model_dump(exclude_none=True)`. This affects three write paths:

- `create_document` — new document creation
- `patch_document` — merged body after a PATCH
- `publish_singleton` — singleton create+publish

This means a field that was never set is never written to the stored JSON body. A PATCH that
omits a field leaves that field unchanged. A PATCH that explicitly sends `"field": null` writes
`null` into the body — this is the one remaining way to store `null`, and it is intentional.

### 2. Explicit `null` on PATCH is preserved as a signal

When a caller sends `PATCH /api/documents/{id}` with `{"body": {"end_date": null}}`, the `null`
value is written to the stored body. The API then returns `"end_date": null` for that document.
This is the only way `null` appears in a document body, and it carries the meaning: "this field
was deliberately cleared."

Consumers that need to distinguish "never set" from "explicitly cleared" can now do so:

- **Absent key** → never set, or set before this field existed in the schema
- **`null` value** → explicitly cleared by a write

---

## API behavior after this change

```python
# Document created with only required fields
POST /api/documents
{ "doc_type": "experience_entry", "body": { "slug": "acme-2024", "company": "Acme", ... } }

# Response — optional fields absent, not nulled
{
  "slug": "acme-2024",
  "company": "Acme",
  "title": "Engineer",
  "start_date": "2022",
  "employment_type": "full-time"
  # end_date, description, location — absent
}

# Explicitly clearing a field
PATCH /api/documents/{id}
{ "body": { "end_date": null } }

# Response — null is now meaningful
{
  "slug": "acme-2024",
  ...
  "end_date": null   # intentionally cleared — this role has no end date
}
```

---

## Impact on consumers

**Astro Content Layer / Zod schemas:** Optional fields can now use `.optional()` cleanly,
without `.nullable()`. The only fields that need `z.string().nullable()` are fields where `null`
has explicit domain meaning (e.g. `end_date: null` meaning "current role"). All other optional
fields become simply `z.string().optional()`.

**LLM agents reading documents:** An absent field signals "not addressed." A `null` field
signals "explicitly cleared." Prompts can be written to treat these differently — e.g. "fill in
any absent optional fields you have information for, but do not overwrite null values unless
instructed."

**Existing documents in the database:** Documents stored before this change may have `null`
values for fields that were never set. These are indistinguishable from intentional `null`s.
A migration is not required — the ambiguity only exists in the historical data, and new writes
will be clean. If strict disambiguation is needed, a one-time migration script can remove
`null` values from existing document bodies.

---

## Rejected alternatives

**1. Strip nulls in the loader / consumer:**
The Astro loader could call `Object.fromEntries(entries.filter(([_, v]) => v !== null))` before
passing data to Zod. Rejected because: this pushes a CMS serialization concern into every
consumer. Every new integration must remember to strip nulls. The fix belongs at the source.

**2. Ban `null` entirely — treat it as a validation error:**
Reject any PATCH that sends a `null` value. Rejected because: explicit null is a valid and
useful signal for "this field was deliberately cleared." Banning it loses the distinction
entirely and forces consumers to use sentinel strings like `""` instead, which is worse.

**3. Add a `mode` parameter to the API (`?null_mode=omit|include`):**
Let the caller decide whether to receive nulls. Rejected because: the source of truth is the
stored body, and it should be consistent. Different consumers seeing different shapes of the
same document is a maintenance hazard.

---

## Interaction with existing ADRs

**ADR 010 (DocumentRef):** `on_delete="nullify"` sets a `DocumentRef` field to `null` in
referencing documents when the target is deleted. This is an intentional `null` write and is
consistent with this ADR — the `null` in a `DocumentRef` field after nullification signals
"the referenced document was deleted."

**ADR 014 (append_only documents):** Append-only documents are written once and never patched.
`model_dump(exclude_none=True)` at creation time means their stored bodies are already clean.
No interaction issue.

---

## Consequences

**Positive:**
- Consumer Zod schemas can be written strictly — `.optional()` without `.nullable()` on
  fields that have no domain reason to be null
- LLM-authored documents carry intent signal: absent = not addressed, null = deliberate
- Stored document bodies are smaller and easier to read
- API responses match the shape of industry-standard headless CMSes (Contentful, Sanity)

**Negative / tradeoffs:**
- Existing stored documents may have historical `null` values that are now ambiguous
- Code that checks `if doc.field === null` to mean "not set" must be updated to check
  `if doc.field === undefined || doc.field === null`

**Neutral:**
- The change is two lines in `documents.py`. No schema migration required.
- Tests that assert `null` appears in responses for unset fields must be updated to assert
  key absence instead.
