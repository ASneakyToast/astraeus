# EPIC-001 — VPP MVP: Governed Data Platform Primitives

**Status:** Ready for implementation  
**Date:** 2026-06-13  
**Target:** USAA VPP POC (Tier 1 → Tier 2)  
**Packages:** `starlette-cms`

---

## Overview

Enable Astraeus to serve as the governed data backend for the USAA VPP underwriting demo. This
epic adds the foundational primitives that unlock all five VPP use cases — structured intake
forms, singleton governed config, document references, immutable fields, and supporting field
types.

**Nothing in this epic requires architectural changes.** All work extends the existing
`fields.py`, `model_builder.py`, `registry.py`, `tables.py`, and `api/documents.py` without
breaking existing behaviour or tests.

---

## Scope

### In scope (Tier 1 + Tier 2)

| Story | Primitive | Use case unlocked |
|---|---|---|
| [STORY-001](stories/STORY-001-field-types.md) | `NumberField`, `SelectField`, `BoolField`, `URLField`, `JSONField` | Intake forms, rule config, test cases |
| [STORY-002](stories/STORY-002-singleton-documents.md) | `singleton=True` block modifier + `get_singleton()` | Rule governance, prompt versioning |
| [STORY-003](stories/STORY-003-immutable-fields.md) | `immutable=True` on `_BaseField` | Eval dataset integrity |
| [STORY-004](stories/STORY-004-document-references.md) | `DocumentRef(block_type)` field type | Eval dataset, test case library |
| [STORY-005](stories/STORY-005-list-filters.md) | `documents.list()` filter params + `active` field support | Test case CI integration |
| [STORY-006](stories/STORY-006-testing-utilities.md) | Phase 4 `BlockTestCase` / `RegistryTestCase` | All VPP blocks testable |

### Out of scope (Tier 3 — follow-on epic)

- ADR 012: `identity` / `permission` callables (multi-author)
- ADR 013 pt.2: field allowlist from `permission` return value
- Parameterized singleton (`step` discriminator) — ADR 009 extension
- MCP server (Phase 5)
- starlette-editor (Phase 10+)

---

## Dependency order

```
STORY-001 (field types)
    │
    ├─ STORY-002 (singletons)       ← depends on registry changes in STORY-001
    │
    ├─ STORY-003 (immutable fields) ← depends only on _BaseField from STORY-001
    │
    └─ STORY-004 (DocumentRef)      ← depends on field types + tables
            │
            └─ STORY-005 (list filters)  ← depends on DocumentRef patterns

STORY-006 (testing utilities) ← independent, but easier after STORY-001
```

Stories 001, 003, and 006 can run in parallel. Story 002 gates on 001. Story 004 gates on 001.
Story 005 gates on 004.

---

## Acceptance criteria (Epic-level)

The following must all pass before EPIC-001 is complete:

- [ ] `uv run pytest packages/starlette-cms/` — all tests green
- [ ] `uv run pyright packages/starlette-cms/` — zero type errors
- [ ] `uv run ruff check packages/starlette-cms/` — zero lint errors
- [ ] The following block definition compiles and validates:

```python
from starlette_cms.fields import (
    NumberField, SelectField, BoolField, URLField,
    JSONField, DocumentRef, ListField
)
from starlette_cms.decorators import block

@block("jewelry_item")
class JewelryItem:
    declared_value: NumberField(label="Declared Value ($)", required=True, min_value=0)
    storage_location: SelectField(
        label="Storage Location",
        choices=["bank_vault", "home_safe", "standard", "daily_wear"],
        required=True
    )
    item_description: str = None  # TextField fallback
    carat: NumberField(label="Carat Weight", required=False)
    photo_urls: ListField(item_type=URLField(), max_items=3, label="Photos")
    has_appraisal: BoolField(label="Has Appraisal", default=False)
    appraisal_doc_url: URLField(label="Appraisal Document", required=False)

@block("storage_rates", singleton=True)
class StorageRates:
    bank_vault: NumberField(label="Bank Vault Rate", precision=4, default=0.005)
    home_safe: NumberField(label="Home Safe Rate", precision=4, default=0.010)

@block("eval_entry")
class EvalEntry:
    submission_ref: DocumentRef(block_type="jewelry_item", label="Submission", immutable=True)
    score: SelectField(choices=["1","2","3","4","5"], label="Score")
    notes: str = None

@block("test_scenario")
class TestScenario:
    label: str = None
    form_data: JSONField(label="Form Data")
    expected_uw_status: SelectField(choices=["auto_approved","manual_review"])
    active: BoolField(label="Active", default=True)
```

- [ ] `cms.documents.get_singleton("storage_rates")` returns the published document
- [ ] PATCHing `submission_ref` on an `eval_entry` is silently ignored (immutable)
- [ ] `cms.documents.list("test_scenario", filters={"active": True})` returns only active scenarios
- [ ] `DocumentRef` raises `DocumentNotFound` when target ID does not exist on create

---

## Testing strategy

Every story includes a `tests/` section. The full test suite must:

1. **Unit tests** — field type Pydantic generation correctness (`test_block_decorator.py`)
2. **Integration tests** — HTTP endpoint behaviour (`test_documents.py`)
3. **Schema tests** — `GET /api/schema/{type}` returns correct `cms:field_meta` extensions
4. **Negative tests** — validation failures return correct 422 with detail

Use `RegistryTestCase` (once STORY-006 is complete) for all block-level tests. Use
`httpx.AsyncClient` with `ASGITransport` for all HTTP tests.

---

## File change map

| File | Stories that touch it |
|---|---|
| `starlette_cms/fields.py` | 001, 003, 004 |
| `starlette_cms/model_builder.py` | 001, 003, 004 |
| `starlette_cms/registry.py` | 002 |
| `starlette_cms/app.py` | 002 |
| `starlette_cms/tables.py` | 002, 004 |
| `starlette_cms/api/documents.py` | 002, 003, 004, 005 |
| `starlette_cms/api/schema.py` | 001, 003 |
| `starlette_cms/exceptions.py` | 002, 004 |
| `starlette_cms/testing/helpers.py` | 006 |
| `starlette_cms/__init__.py` | 001, 002, 004 (exports) |
| `tests/test_block_decorator.py` | 001, 003, 004 |
| `tests/test_documents.py` | 002, 003, 004, 005 |
| `tests/test_schema.py` | 001, 003 |

---

## Definition of done

- All acceptance criteria above are checked
- Each story's individual definition of done is met
- `docs/roadmap.md` Phase 4 items checked as complete
- `CLAUDE.md` current status updated to reflect Phase 4 complete
- No regressions in Phases 1–3 test coverage
