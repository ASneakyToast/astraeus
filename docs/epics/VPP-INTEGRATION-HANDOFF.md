# VPP Integration Handoff — usaa-vpp Repo

**Context:** The Astraeus platform (`starlette-cms`) now ships all the primitives
needed for the VPP underwriting POC. This document tells you how to integrate them
into the `usaa-vpp` FastAPI application. All work described here happens in the
**usaa-vpp repo**, not in Astraeus itself.

**What Astraeus already provides (do not reimplement):**
- Field types: `TextField`, `RichTextField`, `ImageField`, `NumberField`, `SelectField`, `BoolField`, `URLField`, `JSONField`, `ListField`, `DocumentRef`
- Document CRUD API: `GET/POST/PATCH/DELETE /api/documents`, publish/unpublish
- Singleton documents: `@cms.block("name", singleton=True)`, archive-then-activate publish, `GET /api/singletons/{block_type}`
- Immutable fields: `immutable=True` on any field, stripped on PATCH
- DocumentRef: typed foreign keys with `on_delete="block"|"nullify"|"cascade"`, bulk resolution via `resolve_refs` query param
- List filters: `filters=` JSON param, `filter[key]=value` bracket syntax, `order_by`/`order`
- Schema introspection: `GET /api/schema`, `GET /api/schema/{block_type}` with `cms:field_meta`
- Webhooks: `POST /api/webhooks` registration, fires on `document.created/updated/deleted/published/unpublished`
- Testing utilities: `validate_block()`, `BlockTestCase`, `RegistryTestCase`
- Schema versioning + migration runner

**Astraeus version:** Use the latest from the `main` branch of `github.com/ASneakyToast/astraeus`. Point at it via `[tool.uv.sources]` in `pyproject.toml` during development.

---

## Overview

There are 5 integration layers, in dependency order:

1. **Mount CMS** — create a CMS instance and mount it into the FastAPI app
2. **Block definitions** — register all VPP block types
3. **Seed scripts** — populate initial data from existing hardcoded constants and fixtures
4. **Engine wiring** — swap hardcoded constants for CMS queries in the underwriting engine
5. **Frontend changes** — replace hardcoded presets with live CMS queries in dev-gui

Work them in order. Each layer is independently testable before moving on.

---

## 1. Mount CMS into FastAPI

Create `usaa_vpp/cms/app.py`:

```python
from __future__ import annotations

from starlette_cms import CMS

cms = CMS(
    database_url="sqlite:///vpp_content.db",
    auth="none",          # POC — no auth needed for internal use
)
```

In your FastAPI entry point (likely `usaa_vpp/main.py` or `app.py`), mount it:

```python
from usaa_vpp.cms.app import cms

# Mount Astraeus as a sub-application
app.mount("/cms", cms.app)

# Add CMS lifespan to your existing lifespan
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    async with cms.lifespan_context(app):
        # ... your existing startup/shutdown ...
        yield
```

**Verify:** Start the server. `GET /cms/api/schema` should return `{}` (no blocks registered yet).

---

## 2. Block Definitions

Create these files under `usaa_vpp/cms/`. Import and register all blocks before
the app starts (e.g. import them in `usaa_vpp/cms/__init__.py` or in the CMS app module).

### 2a. Item blocks — `usaa_vpp/cms/blocks.py`

```python
from __future__ import annotations

from usaa_vpp.cms.app import cms
from starlette_cms import (
    TextField, NumberField, SelectField, BoolField, URLField, ListField,
)


@cms.block("jewelry_item")
class JewelryItem:
    declared_value:     float = NumberField(label="Declared Value ($)", required=True, min_value=0,
                                           help_text="Full replacement value as appraised")
    storage_location:   str   = SelectField(label="Storage Location",
                                            choices=["bank_vault", "home_safe", "standard", "daily_wear"],
                                            required=True)
    item_description:   str   = TextField(label="Item Description", required=True)
    carat:              float = NumberField(label="Carat Weight", required=False)
    color_grade:        str   = TextField(label="Color Grade (GIA)", required=False)
    clarity_grade:      str   = TextField(label="Clarity Grade (GIA)", required=False)
    metal_type:         str   = SelectField(label="Metal Type",
                                            choices=["14K White Gold", "14K Yellow Gold",
                                                     "18K White Gold", "Platinum"],
                                            required=False)
    photo_urls:         list  = ListField(item_type=URLField(), max_items=3, label="Photos")
    appraisal_doc_url:  str   = URLField(label="Appraisal Document", required=False)
    gia_doc_url:        str   = URLField(label="GIA Certificate", required=False)
```

### 2b. Config blocks — `usaa_vpp/cms/config_blocks.py`

```python
from __future__ import annotations

from usaa_vpp.cms.app import cms
from starlette_cms import (
    TextField, NumberField, SelectField, ListField,
)


@cms.block("storage_rates", singleton=True)
class StorageRates:
    bank_vault: float = NumberField(label="Bank Vault Rate",  default=0.005, precision=4,
                                    help_text="0.50% — climate-controlled, 24hr security")
    home_safe:  float = NumberField(label="Home Safe Rate",   default=0.010, precision=4,
                                    help_text="1.00% — UL-rated safe, fixed to structure")
    standard:   float = NumberField(label="Standard Rate",    default=0.015, precision=4,
                                    help_text="1.50% — drawer, shelf, unlocked cabinet")
    daily_wear: float = NumberField(label="Daily Wear Rate",  default=0.020, precision=4,
                                    help_text="2.00% — worn or carried regularly")


@cms.block("global_thresholds", singleton=True)
class GlobalThresholds:
    scheduled_threshold:            float = NumberField(label="Blanket -> Scheduled ($)",             default=10_000)
    manual_review_threshold:        float = NumberField(label="Auto-approve Ceiling ($)",             default=25_000)
    appraisal_max_age_standard:     float = NumberField(label="Appraisal Max Age - Standard (days)",  default=730)
    appraisal_max_age_high_value:   float = NumberField(label="Appraisal Max Age - High Value (days)",default=365)
    appraisal_high_value_threshold: float = NumberField(label="Appraisal High-Value Floor ($)",       default=10_000)
    min_usd_per_carat:              float = NumberField(label="Min USD/ct (Reasonableness)",          default=500)
    max_usd_per_carat:              float = NumberField(label="Max USD/ct (Reasonableness)",          default=250_000)


@cms.block("category_config")
class CategoryConfig:
    category:             str  = SelectField(label="Category",
                                             choices=["jewelry", "bikes", "cameras",
                                                      "guns_bows", "instruments", "watches"])
    high_value_threshold: float = NumberField(label="High-Value Threshold ($)")
    gia_required_above:   float = NumberField(label="GIA Required Above ($)", required=False)
    photo_slots:          list  = ListField(item_type=TextField(), label="Photo Slot Labels")


@cms.block("risk_rule")
class RiskRule:
    priority:    float = NumberField(label="Priority (lower = evaluated first)")
    risk_level:  str   = SelectField(label="Risk Level", choices=["low", "medium", "high"])
    min_value:   float = NumberField(label="Min Declared Value ($)", required=False)
    storage:     str   = SelectField(label="Storage Location",
                                     choices=["bank_vault", "home_safe", "standard", "daily_wear"],
                                     required=False)
    description: str   = TextField(label="Human description of this rule")
```

### 2c. Test scenario block — `usaa_vpp/cms/scenario_blocks.py`

```python
from __future__ import annotations

from usaa_vpp.cms.app import cms
from starlette_cms import (
    TextField, NumberField, SelectField, BoolField, JSONField, ListField, DocumentRef,
)


@cms.block("test_scenario")
class TestScenario:
    label:        str  = TextField(label="Scenario Name",
                                   help_text="Short, human-readable. E.g. '1ct Diamond Solitaire - GIA present'")
    category:     str  = SelectField(label="Category",
                                     choices=["jewelry", "bikes", "cameras",
                                              "guns_bows", "instruments", "watches"])
    rationale:    str  = TextField(label="Why this scenario exists",
                                   help_text="What edge case, incident, or product decision does this encode?")

    # Input
    form_data:      dict = JSONField(label="Form Data (UnderwriteRequest shape)", required=True)
    appraisal_data: dict = JSONField(label="Appraisal Data", required=False)
    gia_data:       dict = JSONField(label="GIA Data", required=False)

    # Expected outputs
    expected_uw_status:  str   = SelectField(choices=["auto_approved", "manual_review"],
                                             label="Expected Decision")
    expected_risk_level: str   = SelectField(choices=["low", "medium", "high"],
                                             label="Expected Risk Level")
    expected_premium:    float = NumberField(label="Expected Premium ($)", required=False)
    expected_flags:      list  = ListField(item_type=TextField(), label="Expected Flags", required=False)

    # Governance metadata
    rule_config_ref: str  = DocumentRef(block_type="global_thresholds",
                                        label="Rule Config This Scenario Was Written For")
    source:          str  = SelectField(label="Source",
                                        choices=["authored", "derived_from_real_claim",
                                                 "ai_generated", "migrated"])
    active:          bool = BoolField(label="Active (include in CI runs)", default=True)
```

### 2d. Eval block — `usaa_vpp/cms/eval_blocks.py`

```python
from __future__ import annotations

from usaa_vpp.cms.app import cms
from starlette_cms import (
    TextField, NumberField, SelectField, ListField, DocumentRef,
)


@cms.block("eval_entry")
class EvalEntry:
    # References to other governed artifacts
    submission_ref:  str  = DocumentRef(block_type="jewelry_item", label="Submission",
                                        immutable=True)
    rule_config_ref: str  = DocumentRef(block_type="global_thresholds", label="Rule Config Version")

    # Workflow output snapshot
    uw_status:       str   = SelectField(choices=["auto_approved", "manual_review"], label="Decision")
    annual_premium:  float = NumberField(label="Annual Premium ($)", required=False)
    uw_flags:        list  = ListField(item_type=TextField(), label="Flags")

    # Human judgment
    score:            str = SelectField(choices=["1", "2", "3", "4", "5"], label="Quality Score (1-5)")
    correct_decision: str = SelectField(choices=["yes", "no", "borderline"],
                                        label="Was the decision correct?")
    notes:            str = TextField(label="Reviewer Notes", required=False)
    reviewer:         str = TextField(label="Reviewer", required=False)
```

### 2e. Prompt block — `usaa_vpp/cms/prompt_blocks.py`

```python
from __future__ import annotations

from usaa_vpp.cms.app import cms
from starlette_cms import TextField, NumberField, SelectField


@cms.block("uw_prompt")
class UwPrompt:
    step:              str   = SelectField(label="Pipeline Step",
                                           choices=["intake", "fraud_detection", "pricing",
                                                    "consistency", "orchestration"])
    system:            str   = TextField(label="System Prompt", required=False,
                                         help_text="The system message sent to the model")
    user_template:     str   = TextField(label="User Prompt Template",
                                         help_text="Jinja2 template - use {{ variable }} for runtime substitution")
    model:             str   = TextField(label="Model ID",
                                         help_text="e.g. riky-vibe, claude-opus-4-8")
    temperature:       float = NumberField(label="Temperature", default=0.0, precision=2)
    max_tokens:        float = NumberField(label="Max Tokens", default=4096)
    change_rationale:  str   = TextField(label="What changed and why",
                                         help_text="Required on publish")
    authored_by:       str   = TextField(label="Domain expert who authored this version", required=False)
```

> **Note on prompt versioning:** The use case doc describes `UwPrompt` as a
> parameterized singleton (one active doc per `step` value). Astraeus doesn't yet
> enforce that constraint at the DB level. For the POC, register it as a regular
> block (not `singleton=True`) and use
> `cms.documents.list("uw_prompt", filters={"step": "intake"}, published=True, limit=1)`
> to fetch the latest published prompt for a given step. This works correctly; it
> just doesn't prevent two prompts for the same step from being published
> simultaneously. Acceptable for POC.

### 2f. Wire up imports — `usaa_vpp/cms/__init__.py`

```python
from usaa_vpp.cms.app import cms
from usaa_vpp.cms import blocks
from usaa_vpp.cms import config_blocks
from usaa_vpp.cms import scenario_blocks
from usaa_vpp.cms import eval_blocks
from usaa_vpp.cms import prompt_blocks
```

Import this package in your FastAPI startup so all blocks are registered before the
CMS app is accessed.

**Verify:** Start the server. `GET /cms/api/schema` should list all block types.
`GET /cms/api/schema/jewelry_item` should return the full JSON Schema with
`cms:field_meta` extensions (labels, choices, help_text).

---

## 3. Seed Scripts

These are one-time scripts to populate the CMS with initial data from existing
hardcoded values.

### 3a. Seed rule config — `usaa_vpp/cms/seed.py`

Extracts current hardcoded constants from `lib/underwriting.py` (or wherever
`STORAGE_RATES`, `THRESHOLDS`, etc. live) and publishes them as singleton documents.

```python
from __future__ import annotations

from usaa_vpp.cms.app import cms


async def seed_config():
    """Seed initial rule configuration from hardcoded constants."""
    from starlette.testclient import TestClient
    # Or use httpx.AsyncClient against the running app

    # StorageRates
    await _create_and_publish("storage_rates", {
        "bank_vault": 0.005,
        "home_safe": 0.010,
        "standard": 0.015,
        "daily_wear": 0.020,
    })

    # GlobalThresholds
    await _create_and_publish("global_thresholds", {
        "scheduled_threshold": 10_000,
        "manual_review_threshold": 25_000,
        "appraisal_max_age_standard": 730,
        "appraisal_max_age_high_value": 365,
        "appraisal_high_value_threshold": 10_000,
        "min_usd_per_carat": 500,
        "max_usd_per_carat": 250_000,
    })

    print("Config seeded.")


async def _create_and_publish(block_type: str, body: dict):
    """Create a document via the HTTP API and publish it."""
    # Use the CMS's internal document API directly:
    # POST /api/documents, then POST /api/documents/{id}/publish
    # OR use cms._db + the tables directly for seeding.
    #
    # Adapt this to however your app makes internal CMS calls.
    # The simplest approach for seeding is httpx against the mounted app.
    pass
```

> **Implementation note:** The exact mechanism depends on your app's structure.
> The cleanest approach is an `httpx.AsyncClient` with `ASGITransport` pointed at
> the CMS app, making real API calls. Alternatively, write directly to the database
> using Piccolo ORM (`CMSDocument.insert()`). Either works for seeding.

### 3b. Seed test scenarios — `usaa_vpp/cms/seed_scenarios.py`

Migrate from two sources:
1. **TypeScript presets** in `dev-gui/front-end/src/pages/UnderwritePage.tsx` (lines ~80-161) — the `PRESETS` array
2. **JSON fixture files** in `tests/data/rules_matrix/*.json`

For each, create a `test_scenario` document with `source="migrated"`.

### 3c. Seed prompts — `usaa_vpp/cms/seed_prompts.py`

Extract prompt text from the five Pkl workflow files:
- `workflows/vpp_intake.pkl`
- `workflows/vision_dox.pkl`
- `workflows/pricing_test.pkl`
- `workflows/uw_consistency.pkl`
- `workflows/underwriting.pkl`

Create one `uw_prompt` document per step, with `step`, `system`, `user_template`,
`model`, `temperature`, and `max_tokens` populated from the Pkl source.

---

## 4. Engine Wiring

### 4a. Replace hardcoded rates with CMS singleton lookup

Wherever the underwriting engine currently reads constants like `STORAGE_RATES`:

```python
# Before:
STORAGE_RATES = {"bank_vault": 0.005, "home_safe": 0.010, ...}

def calculate_premium(declared_value: float, storage: str) -> float:
    rate = STORAGE_RATES[storage]
    return round(declared_value * rate, 2)

# After:
from usaa_vpp.cms.app import cms

_rates_cache: dict | None = None

async def get_storage_rates() -> dict:
    global _rates_cache
    if _rates_cache is None:
        doc = await cms.documents.get_singleton("storage_rates")
        _rates_cache = doc["body"]
    return _rates_cache

async def invalidate_rates():
    global _rates_cache
    _rates_cache = None

async def calculate_premium(declared_value: float, storage: str) -> float:
    rates = await get_storage_rates()
    return round(declared_value * rates[storage], 2)
```

Do the same for `global_thresholds` and any other hardcoded config.

### 4b. Add webhook handler for cache invalidation

Register a webhook receiver endpoint in your FastAPI app:

```python
@app.post("/webhooks/cms")
async def cms_webhook(request: Request):
    payload = await request.json()
    event = payload.get("event")
    block_type = payload.get("document_type")

    if event == "document.published":
        if block_type == "storage_rates":
            await invalidate_rates()
        elif block_type == "global_thresholds":
            await invalidate_thresholds()
        elif block_type in ("risk_rule", "category_config"):
            await invalidate_rules()

    return {"ok": True}
```

Then register it with the CMS (on startup or via seed script):

```
POST /cms/api/webhooks
{
  "url": "http://localhost:8000/webhooks/cms",
  "events": ["document.published"]
}
```

### 4c. Prompt loader (for prompt versioning)

```python
# lib/prompt_loader.py
from __future__ import annotations

from usaa_vpp.cms.app import cms

_prompt_cache: dict[str, dict] = {}

async def get_prompt(step: str) -> dict:
    if step not in _prompt_cache:
        docs = await cms.documents.list(
            "uw_prompt",
            filters={"step": step},
            published=True,
            limit=1,
        )
        if not docs:
            raise ValueError(f"No published prompt for step {step!r}")
        _prompt_cache[step] = docs[0]
    return _prompt_cache[step]

async def invalidate_prompts(step: str | None = None):
    if step:
        _prompt_cache.pop(step, None)
    else:
        _prompt_cache.clear()
```

### 4d. CI scenario runner (for test case library)

```python
# ci/run_scenarios.py
from __future__ import annotations

from usaa_vpp.cms.app import cms


async def run_scenarios_against_config(proposed_config: dict) -> dict:
    scenarios = await cms.documents.list(
        "test_scenario",
        filters={"active": True},
        limit=500,
    )

    results = []
    for s in scenarios:
        body = s["body"]
        actual = apply_rules(body["form_data"], body.get("appraisal_data"), config=proposed_config)
        passed = actual.uw_status == body["expected_uw_status"]
        results.append({
            "id": s["id"],
            "label": body["label"],
            "passed": passed,
            "actual": actual.uw_status,
            "expected": body["expected_uw_status"],
        })

    return {
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": [r for r in results if not r["passed"]],
    }
```

---

## 5. Frontend Changes (dev-gui React)

### 5a. Schema-driven form hook

```typescript
// src/hooks/useBlockSchema.ts
export function useBlockSchema(blockType: string) {
  const [schema, setSchema] = useState(null);
  useEffect(() => {
    fetch(`/cms/api/schema/${blockType}`)
      .then(r => r.json())
      .then(data => setSchema(data.schema));
  }, [blockType]);
  return schema;
}
```

### 5b. Replace hardcoded presets in `UnderwritePage.tsx`

```typescript
// Before (lines ~80-161):
const PRESETS = [
  { label: '1ct Diamond Solitaire', category: 'jewelry', declaredValue: 8000, ... },
  ...
];

// After:
const { data: presets } = useDocumentList("test_scenario", { active: true });
```

### 5c. SchemaForm component

Build a generic `SchemaForm` component that reads `cms:field_meta` from the schema
response and renders appropriate form controls:
- `SelectField` choices -> `<select>` dropdown
- `NumberField` -> `<input type="number">` with min/max
- `BoolField` -> checkbox
- `TextField` -> `<input type="text">` or `<textarea>`

This replaces the hardcoded field arrays currently in the underwrite page.

---

## Verification Checklist

After each layer, verify before moving on:

- [ ] **Layer 1:** `GET /cms/api/schema` returns `{}`
- [ ] **Layer 2:** `GET /cms/api/schema` lists all block types; `GET /cms/api/schema/jewelry_item` returns full schema with `cms:field_meta`
- [ ] **Layer 3:** `GET /cms/api/singletons/storage_rates` returns seeded rates; `GET /cms/api/documents?type=test_scenario` returns migrated scenarios
- [ ] **Layer 4:** Underwriting engine reads rates from CMS instead of constants; publishing new rates via `POST /cms/api/singletons/storage_rates/publish` invalidates the cache; `calculate_premium()` returns updated values
- [ ] **Layer 5:** Underwrite page renders fields from schema API; preset picker loads scenarios from CMS

---

## What This Does NOT Cover

- **starlette-editor** (no visual editing UI — all content is managed via API for the POC)
- **MCP server** (no agent tooling — that's Astraeus Phase 5)
- **mediakit** (no image/asset management)
- **Parameterized singleton enforcement** (prompt versioning works via filters, but doesn't prevent two prompts for the same step from being published simultaneously)
- **Production auth** (POC uses `auth="none"`)
- **Production deployment** (POC runs locally)

---

## Key API Patterns Reference

### Create a document
```
POST /cms/api/documents
Content-Type: application/json

{
  "type": "jewelry_item",
  "body": { "declared_value": 8000, "storage_location": "home_safe", ... }
}
```

### Publish a document
```
POST /cms/api/documents/{id}/publish
```

### Publish a singleton (creates new version, archives previous)
```
POST /cms/api/singletons/storage_rates/publish
Content-Type: application/json

{
  "body": { "bank_vault": 0.006, "home_safe": 0.011, ... },
  "version_message": "Increased rates 20% per Q3 actuarial review"
}
```

### Get active singleton
```
GET /cms/api/singletons/storage_rates
```

### List with filters
```
GET /cms/api/documents?type=test_scenario&filter[active]=true&filter[category]=jewelry
```

### List with JSON filters + ordering
```
GET /cms/api/documents?type=eval_entry&filters={"score":"1"}&order_by=created_at&order=desc
```

### List with resolved references
```
GET /cms/api/documents?type=eval_entry&resolve_refs=submission_ref,rule_config_ref
```

### Python accessor
```python
rates = await cms.documents.get_singleton("storage_rates")
rate = rates["body"]["bank_vault"]  # 0.005

scenarios = await cms.documents.list(
    "test_scenario",
    filters={"active": True, "category": "jewelry"},
    published=True,
)
```
