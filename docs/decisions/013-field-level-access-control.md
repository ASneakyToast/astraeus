# ADR 013 — Field-level access control

**Status:** Proposed  
**Date:** 2026-06-13  
**Depends on:** ADR 012 (multi-author identity and permissions) — for the field allowlist mechanism only

---

## Context

ADR 012 adds document-level permission control: can this user perform this operation on this
document? That answers whether a PATCH request is allowed at all, but not which fields within
that PATCH are allowed.

Two distinct patterns emerged from the real use cases that require field-level control:

### Pattern 1 — Immutable fields (EvalEntry)

The `EvalEntry` block stores refs to the submission, rule config, and prompt versions that were
active when a workflow run was scored:

```python
class EvalEntry:
    submission_ref:  DocumentRef(...)   # the item being evaluated
    rule_config_ref: DocumentRef(...)   # which rule version was active
    prompt_refs:     ListField(...)     # which prompt versions were active
    uw_status:       SelectField(...)   # snapshot of the workflow decision
    annual_premium:  NumberField(...)   # snapshot of the computed premium

    score:           SelectField(...)   # writable: reviewer can update
    correct_decision: SelectField(...)  # writable: reviewer can update
    notes:           TextField(...)     # writable: reviewer can update
    reviewer:        TextField(...)     # writable: reviewer can update
```

The first five fields are the *evidence* — they record what was true at evaluation time. If any
of them can be edited after the fact, the eval record loses its integrity as a governed audit
artifact. A score of 5/5 attached to a submission ref that was silently swapped out is
meaningless for counterfactual analysis.

This is **not a permission question** — it applies regardless of who the user is, including
admins. No user should ever be able to change `submission_ref` after an EvalEntry is created.
It is a **field constraint**.

### Pattern 2 — Role-based field write restriction (UwPrompt)

The `UwPrompt` block stores a versioned AI pipeline prompt:

```python
class UwPrompt:
    system:           TextField(...)    # domain expert: yes; engineer: yes
    user_template:    TextField(...)    # domain expert: yes; engineer: yes
    change_rationale: TextField(...)    # domain expert: yes; engineer: yes

    model:       TextField(...)         # domain expert: NO; engineer: yes
    temperature: NumberField(...)       # domain expert: NO; engineer: yes
    max_tokens:  NumberField(...)       # domain expert: NO; engineer: yes
```

A fraud analyst (domain expert) should be able to revise prompt text and record their rationale.
They should not be able to change which model is used or its temperature — those are engineering
decisions with system-wide implications. An engineer or admin can change any field.

This IS a permission question — the answer depends on who the user is. It is a **role-based
field restriction** and depends on the identity system from ADR 012.

---

## Decision

### 1. `immutable=True` field property

`_BaseField` gains an `immutable` boolean (default `False`):

```python
@dataclass
class _BaseField:
    required: bool = False
    label: str | None = None
    immutable: bool = False   # ← new
    # ... other existing fields
```

Fields marked `immutable=True` are **silently stripped from PATCH bodies** before the merge
step in `patch_document`. They are still written on create — `immutable` only prevents
post-creation changes. No error is returned when an immutable field is included in a PATCH;
it is simply ignored, identical to how unknown fields are handled.

Usage:

```python
@cms.block("eval_entry")
class EvalEntry:
    submission_ref:  DocumentRef(..., immutable=True)
    rule_config_ref: DocumentRef(..., immutable=True)
    prompt_refs:     ListField(...,   immutable=True)
    uw_status:       SelectField(..., immutable=True)
    annual_premium:  NumberField(..., immutable=True)

    score:           SelectField(...)   # writable — no immutable flag
    notes:           TextField(...)
```

Immutability is surfaced in the schema API under `cms:field_meta`:

```json
{
  "cms:field_meta": {
    "label": "Submission",
    "immutable": true
  }
}
```

This allows the editor and MCP tools to render immutable fields as read-only without needing
to attempt a PATCH and observe the silence.

### 2. Field allowlist from `permission` callable

ADR 012 defines the `permission` callable signature:

```python
async def permission(request, user, operation, document) -> bool
```

This ADR extends the return type to `bool | list[str]`:

- `True` — user may perform the operation on all fields (current behaviour)
- `False` — user may not perform the operation (current behaviour)
- `list[str]` — user may perform the operation, but only on the named fields

When `permission` returns a field allowlist, the PATCH handler strips any fields from the
request body that are not in the list before the merge step. This is applied **after**
immutable field stripping — immutability always wins.

Usage:

```python
async def permission(request, user, operation, document):
    if operation != "update":
        return user.role in ("engineer", "admin")

    if user.role == "domain_expert":
        return ["system", "user_template", "change_rationale"]
    if user.role in ("engineer", "admin"):
        return True
    return False
```

Like immutable field stripping, disallowed fields are silently dropped from the PATCH body
rather than returning a 422 — this keeps client code simple (send the whole document, the
server keeps what it's allowed to keep) and avoids leaking which fields a user cannot access.

---

## Why silent strip rather than 422

Returning a 422 when a PATCH includes an immutable or disallowed field would require clients
to know exactly which fields they're allowed to send before sending. This pushes policy
awareness into every client — the editor, the MCP agent, external consumers. With silent
stripping, a client can always send the full document body and rely on the server to apply
the right constraints. The schema API exposes immutability so clients that want to give
feedback can still do so; clients that don't care simply work.

This matches how HTML forms handle `disabled` fields: the browser silently omits them from
the submission rather than erroring.

---

## Enforcement point in `patch_document`

Both mechanisms are applied in the same place — before the merge step in `patch_document`:

```python
# 1. Strip immutable fields (field constraint — independent of user)
immutable_fields = get_immutable_fields(doc_model)
for field_name in immutable_fields:
    new_body_data.pop(field_name, None)

# 2. Strip fields outside the permission allowlist (role-based — requires ADR 012)
if cms.permission is not None:
    user = await cms.identity(request) if cms.identity else None
    allowed = await cms.permission(request, user, "update", row)
    if allowed is False:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    if isinstance(allowed, list):
        new_body_data = {k: v for k, v in new_body_data.items() if k in allowed}

# 3. Merge and validate (existing logic)
merged_body = {**existing_body, **new_body_data}
```

Step 1 has no dependency on ADR 012 and can be implemented immediately.
Step 2 is a no-op until `cms.permission` is configured, and requires ADR 012 to be
implemented before it has any effect.

---

## What this does not cover — read-level field hiding

There is a third pattern — hiding fields from GET responses for certain consumers. For
example, internal scoring notes on an EvalEntry that should not be returned to external
API consumers.

This is **deferred**. Read-level field hiding is more complex (it requires filtering the
response body, not just stripping from a write path) and no current use case demands it.
When needed, it would be handled by an extension to `permission` covering `"read"` as an
operation, returning a field allowlist that the GET handler applies before serialising.

---

## Alternatives considered

**Validate and 422 on disallowed fields**
Rejected. Pushes policy awareness into all clients. The schema API already provides
the information clients need to build good UX; a 422 adds error handling requirements
without adding capability.

**Pydantic model variants (one model per role)**
Each role gets a separate Pydantic model with only the fields they can write. Rejected
because: block definitions would need to be duplicated or generated per role; model
selection adds complexity to the create/patch flow; the permission callable is already
the right place for role logic.

**Pydantic `model_config = {"frozen": True}` for immutable models**
Pydantic's frozen mode makes the entire model immutable, not individual fields. Not
applicable here since EvalEntry has a mix of immutable (refs) and mutable (score, notes)
fields.

**Separate `immutable` document type**
Marking an entire document type as append-only (create + publish, no patching). Considered
for future use (audit log entries, signed financial records) but too broad for EvalEntry
where some fields must remain editable after creation.

---

## Consequences

- `_BaseField` gains `immutable: bool = False` — backward compatible, no existing definitions change
- `field_meta()` on `_BaseField` includes `"immutable": True` when set — editor and MCP tools can
  render these fields as read-only
- `patch_document` gains an immutable-field strip step before the merge — a small, isolated change
- The `permission` callable return type is widened to `bool | list[str]` — existing callables
  returning `bool` are unaffected
- Read-level field hiding is explicitly out of scope for this ADR

## Implementation order

1. **`immutable=True`** — implement now, no dependencies. Touches `fields.py` and `patch_document`.
2. **Field allowlist from `permission`** — implement as part of ADR 012 implementation, not before.
