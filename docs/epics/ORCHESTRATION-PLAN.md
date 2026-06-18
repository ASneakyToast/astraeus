# EPIC-001 Agentic Orchestration Plan

**Orchestrator model:** Claude Opus 4.8  
**Sub-agent model:** Claude Sonnet 4.6 (implementation) / Claude Haiku 4.5 (verification)  
**Parallelism:** Phase 1 stories run concurrently; Phase 2 stories gate on Phase 1 output

---

## Overview

This document defines how an Opus orchestrator should delegate EPIC-001 to a fleet of
sub-agents. The orchestrator reads this plan, reads the story files, confirms no blocking
issues, then fans out work to sub-agents using Claude Code's `Agent` tool.

Each sub-agent receives:
1. The story file as its primary spec
2. The relevant source files to read first
3. A strict output contract (what files it must write, what tests it must pass)
4. Isolation mode: `worktree` so agents writing different files don't conflict

---

## Orchestrator responsibilities

1. **Pre-flight check** — read `EPIC-001-vpp-mvp.md`, verify all story files exist, run
   `uv run pytest packages/starlette-cms/` to confirm baseline green
2. **Phase 1 fanout** — dispatch STORY-001, STORY-003, STORY-006 in parallel (no dependencies)
3. **Phase 1 join** — wait for all Phase 1 agents to complete; run full test suite; verify green
4. **Phase 2 fanout** — dispatch STORY-002 (gates on 001) and continue with STORY-006 if not done
5. **Phase 3 sequential** — STORY-004 after STORY-002 (needs singleton registry changes)
6. **Phase 4** — STORY-005 after STORY-004
7. **Final verification** — run full test suite + pyright + ruff; check all epic acceptance criteria
8. **Commit** — commit with conventional commit message per CLAUDE.md

---

## Phase structure

```
Phase 0: Pre-flight
    Orchestrator: run tests, confirm baseline, read all story files

Phase 1: Parallel (no inter-story dependencies)
    Agent-A: STORY-001 — field types
    Agent-B: STORY-003 — immutable fields
    Agent-C: STORY-006 — testing utilities

Phase 1 Gate: Orchestrator joins all Phase 1 agents
    run pytest → must be green before proceeding

Phase 2: Parallel (gates on Phase 1 complete)
    Agent-D: STORY-002 — singleton documents (needs STORY-001 registry)

Phase 2 Gate: Orchestrator joins Phase 2
    run pytest → must be green before proceeding

Phase 3: Sequential
    Agent-E: STORY-004 — DocumentRef (needs STORY-001 fields + STORY-003 immutable)

Phase 3 Gate: Orchestrator joins Phase 3
    run pytest → must be green

Phase 4: Sequential
    Agent-F: STORY-005 — list filters (needs STORY-004 patterns)

Final Gate: Orchestrator runs full acceptance criteria
    pytest + pyright + ruff
    validate epic acceptance criteria block by block
    commit if all green
```

---

## Agent prompts

### Orchestrator bootstrap prompt

```
You are the orchestrator for EPIC-001 (VPP MVP primitives) in the Astraeus monorepo.

Your job:
1. Read /Users/jlithgow/Code/personal/astraeus/docs/epics/EPIC-001-vpp-mvp.md
2. Read all story files in /Users/jlithgow/Code/personal/astraeus/docs/epics/stories/
3. Run the baseline test suite: uv run pytest packages/starlette-cms/ -q
4. If baseline is green, proceed with the orchestration plan in ORCHESTRATION-PLAN.md
5. If baseline is red, STOP and report which tests are failing — do not proceed

Follow ORCHESTRATION-PLAN.md exactly. Do not skip the gate checks.
Report your progress at each phase boundary.
```

---

### Agent-A: STORY-001 — Field Types

**Isolation:** `worktree`  
**Files to read first:**
- `docs/epics/stories/STORY-001-field-types.md`
- `packages/starlette-cms/starlette_cms/fields.py`
- `packages/starlette-cms/starlette_cms/model_builder.py`
- `packages/starlette-cms/starlette_cms/__init__.py`
- `packages/starlette-cms/tests/test_block_decorator.py`
- `packages/starlette-cms/tests/test_schema.py`

**Prompt:**
```
You are implementing STORY-001 (new field types) for the Astraeus starlette-cms package.

Read the story file first:
  docs/epics/stories/STORY-001-field-types.md

Then read the files listed in the story's "Files to read first" section.

Implement exactly what the story specifies:
1. Add NumberField, SelectField, BoolField, URLField, JSONField to fields.py
2. Wire all five through _make_field() in model_builder.py
3. Export all five from starlette_cms/__init__.py
4. Add the tests listed in the story's Tests section

After implementing, run:
  uv run pytest packages/starlette-cms/tests/test_block_decorator.py -v
  uv run pytest packages/starlette-cms/tests/test_schema.py -v

Fix any failures before reporting done.
Report: which files you changed, which tests you added, and the pytest output.
```

---

### Agent-B: STORY-003 — Immutable Fields

**Isolation:** `worktree`  
**Files to read first:**
- `docs/epics/stories/STORY-003-immutable-fields.md`
- `packages/starlette-cms/starlette_cms/fields.py`
- `packages/starlette-cms/starlette_cms/model_builder.py`
- `packages/starlette-cms/starlette_cms/api/documents.py`
- `packages/starlette-cms/tests/test_documents.py`
- `packages/starlette-cms/tests/test_schema.py`

**Prompt:**
```
You are implementing STORY-003 (immutable fields) for the Astraeus starlette-cms package.

Read the story file first:
  docs/epics/stories/STORY-003-immutable-fields.md

Implement exactly what the story specifies:
1. Add immutable: bool = False to _BaseField in fields.py
2. Add get_immutable_fields() helper and __immutable_fields__ on models in model_builder.py
3. Add the immutable-field strip step in patch_document in api/documents.py
4. Add the tests listed in the story's Tests section

IMPORTANT: Do NOT change the patch_document signature or any other logic in documents.py —
only add the strip step before the merge. Do not touch STORY-001 field types work.

After implementing, run:
  uv run pytest packages/starlette-cms/tests/test_documents.py -v -k "immutable"
  uv run pytest packages/starlette-cms/tests/test_schema.py -v -k "immutable"
  uv run pytest packages/starlette-cms/tests/test_block_decorator.py -v -k "immutable"

Fix any failures before reporting done.
Report: which files you changed, tests added, and pytest output.
```

---

### Agent-C: STORY-006 — Testing Utilities

**Isolation:** `worktree`  
**Files to read first:**
- `docs/epics/stories/STORY-006-testing-utilities.md`
- `packages/starlette-cms/starlette_cms/testing/helpers.py`
- `packages/starlette-cms/starlette_cms/testing/__init__.py`
- `packages/starlette-cms/starlette_cms/contrib/blocks/basic.py`

**Prompt:**
```
You are implementing STORY-006 (testing utilities) for the Astraeus starlette-cms package.

Read the story file first:
  docs/epics/stories/STORY-006-testing-utilities.md

Implement exactly what the story specifies:
1. Implement validate_block(), BlockTestCase, and RegistryTestCase in testing/helpers.py
2. Export all three from testing/__init__.py
3. Add tests/test_testing_helpers.py
4. Add tests/test_contrib_blocks.py using BlockTestCase for contrib/blocks/basic.py blocks

After implementing, run:
  uv run pytest packages/starlette-cms/tests/test_testing_helpers.py -v
  uv run pytest packages/starlette-cms/tests/test_contrib_blocks.py -v

Fix any failures before reporting done.
Report: which files you changed, tests added, and pytest output.
```

---

### Agent-D: STORY-002 — Singleton Documents

**Isolation:** `worktree`  
**Pre-condition:** Phase 1 complete and merged (STORY-001 field types must be in place)  
**Files to read first:**
- `docs/epics/stories/STORY-002-singleton-documents.md`
- `docs/decisions/009-singleton-documents.md`
- `packages/starlette-cms/starlette_cms/registry.py`
- `packages/starlette-cms/starlette_cms/app.py`
- `packages/starlette-cms/starlette_cms/tables.py`
- `packages/starlette-cms/starlette_cms/api/documents.py`
- `packages/starlette-cms/starlette_cms/exceptions.py`
- `packages/starlette-cms/tests/test_documents.py`
- `packages/starlette-cms/tests/test_registry.py`

**Prompt:**
```
You are implementing STORY-002 (singleton documents) for the Astraeus starlette-cms package.

Read the story file first:
  docs/epics/stories/STORY-002-singleton-documents.md

Also read the relevant ADR:
  docs/decisions/009-singleton-documents.md

Implement exactly what the story specifies:
1. Add BlockRegistration dataclass and singleton flag to registry.py
2. Update @cms.block() in app.py to accept singleton=True
3. Add singleton_status column to CMSDocument table via migration
4. Update publish_document in api/documents.py to enforce singleton semantics
5. Add GET/POST /api/documents/singleton/{block_type} routes
6. Add GET /api/documents/singleton/{block_type}/history route
7. Add cms.documents.get_singleton() Python accessor
8. Add DocumentNotFound and SingletonConflict to exceptions.py
9. Add all tests from the story's Tests section

After implementing, run:
  uv run pytest packages/starlette-cms/ -v -k "singleton"
  uv run pytest packages/starlette-cms/ -q   # full suite, no regressions

Fix any failures before reporting done.
Report: files changed, tests added, migration file path, and pytest output.
```

---

### Agent-E: STORY-004 — Document References

**Isolation:** `worktree`  
**Pre-condition:** STORY-001 (field types) and STORY-003 (immutable fields) merged  
**Files to read first:**
- `docs/epics/stories/STORY-004-document-references.md`
- `docs/decisions/010-document-references.md`
- `packages/starlette-cms/starlette_cms/fields.py`
- `packages/starlette-cms/starlette_cms/model_builder.py`
- `packages/starlette-cms/starlette_cms/api/documents.py`
- `packages/starlette-cms/starlette_cms/exceptions.py`
- `packages/starlette-cms/tests/test_documents.py`
- `packages/starlette-cms/tests/test_block_decorator.py`
- `packages/starlette-cms/tests/test_schema.py`

**Prompt:**
```
You are implementing STORY-004 (DocumentRef field type) for the Astraeus starlette-cms package.

Read the story file first:
  docs/epics/stories/STORY-004-document-references.md

Also read the relevant ADR:
  docs/decisions/010-document-references.md

Implement exactly what the story specifies:
1. Add DocumentRef to fields.py
2. Wire DocumentRef through _make_field() in model_builder.py; populate __ref_fields__
3. Add _validate_refs() helper and call it in create_document and patch_document
4. Add _check_ref_integrity() to delete_document (on_delete="block" and "nullify")
5. Add resolve_refs query param to list_documents with bulk resolution
6. Export DocumentRef from starlette_cms/__init__.py
7. Add BlockTypeMismatch and ReferencedDocumentError to exceptions.py
8. Add all tests from the story's Tests section

After implementing, run:
  uv run pytest packages/starlette-cms/ -q

Fix any failures before reporting done.
Report: files changed, tests added, and pytest output.
```

---

### Agent-F: STORY-005 — List Filters

**Isolation:** `worktree`  
**Pre-condition:** STORY-004 (DocumentRef) merged  
**Files to read first:**
- `docs/epics/stories/STORY-005-list-filters.md`
- `packages/starlette-cms/starlette_cms/api/documents.py`
- `packages/starlette-cms/starlette_cms/app.py` (for CMSDocuments accessor)
- `packages/starlette-cms/tests/test_documents.py`

**Prompt:**
```
You are implementing STORY-005 (document list filters) for the Astraeus starlette-cms package.

Read the story file first:
  docs/epics/stories/STORY-005-list-filters.md

Implement exactly what the story specifies:
1. Add filters and filter[key]=value query param support to list_documents in api/documents.py
2. Add order_by and order query params
3. Add _coerce_filter_value() and _matches_filters() helpers
4. Add filters_applied to the list response body
5. Add list() method to CMSDocuments accessor in app.py
6. Add all tests from the story's Tests section

After implementing, run:
  uv run pytest packages/starlette-cms/ -q

Fix any failures before reporting done.
Report: files changed, tests added, and pytest output.
```

---

## Orchestrator final verification script

After all agents complete and their changes are merged, the orchestrator runs:

```bash
# 1. Full test suite
uv run pytest packages/starlette-cms/ -v

# 2. Type checks
uv run pyright packages/starlette-cms/

# 3. Lint
uv run ruff check packages/starlette-cms/
uv run ruff format --check packages/starlette-cms/

# 4. Epic acceptance criteria smoke test
uv run python - <<'EOF'
from starlette_cms.fields import (
    NumberField, SelectField, BoolField, URLField, JSONField, DocumentRef, ListField
)
from starlette_cms.decorators import block

@block("jewelry_item")
class JewelryItem:
    declared_value: float = NumberField(label="Declared Value ($)", required=True, min_value=0)
    storage_location: str = SelectField(
        label="Storage Location",
        choices=["bank_vault", "home_safe", "standard", "daily_wear"],
        required=True
    )
    has_appraisal: bool = BoolField(label="Has Appraisal", default=False)
    photo_urls: list = ListField(item_type=URLField(), label="Photos")

@block("storage_rates", singleton=True)
class StorageRates:
    bank_vault: float = NumberField(label="Bank Vault Rate", precision=4, default=0.005)
    home_safe: float = NumberField(label="Home Safe Rate", precision=4, default=0.010)

@block("test_scenario")
class TestScenario:
    form_data: dict = JSONField(label="Form Data", required=True)
    expected_uw_status: str = SelectField(choices=["auto_approved","manual_review"], required=True)
    active: bool = BoolField(label="Active", default=True)

print("✅ All VPP blocks compile successfully")
print(f"  JewelryItem singleton: {getattr(JewelryItem, '__singleton__', False)}")
print(f"  StorageRates singleton: {getattr(StorageRates, '__singleton__', False)}")
EOF
```

---

## Conflict resolution rules

If two agents modify the same file (unlikely with worktrees but possible at merge time):

1. `fields.py` — STORY-001 and STORY-003 both touch it. Merge rule: STORY-001 adds new
   classes, STORY-003 adds `immutable` to `_BaseField`. These are non-overlapping edits.
   Apply STORY-001 first, then STORY-003.

2. `model_builder.py` — STORY-001 adds branches to `_make_field`, STORY-003 adds
   `get_immutable_fields` and `__immutable_fields__`. Non-overlapping. STORY-001 first.

3. `api/documents.py` — STORY-003 adds immutable strip in `patch_document`, STORY-002 adds
   singleton path in `publish_document`, STORY-004 adds ref validation, STORY-005 adds filter
   logic. All are additions to different functions or pre-existing blocks. Apply in story order.

4. `tests/test_documents.py` — all agents append new test functions. No conflict if each
   agent appends to the end of the file. Orchestrator verifies no duplicate function names.

---

## Failure handling

If an agent fails or produces red tests:

1. Orchestrator reads the agent's output and error log
2. Sends a follow-up `SendMessage` with specific correction instructions
3. If the agent cannot fix within 2 follow-up rounds, orchestrator implements the fix itself
4. Gates never advance until the test suite is green

If a gate check fails (tests red after a phase):

1. Orchestrator identifies which new tests are failing
2. Maps failures to the responsible story/agent
3. Issues correction instructions before advancing
