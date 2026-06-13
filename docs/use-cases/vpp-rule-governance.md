# Use Case: Governed Rule Configuration (USAA VPP Underwriting Rules)

**Status:** POC planned  
**Explored:** 2026-06-13  
**Related:** [`vpp-underwriting-intake.md`](./vpp-underwriting-intake.md)  
**Packages:** `starlette-cms` (core)  
**Roadmap impact:** Introduces singleton document pattern (Phase 4/5); seeds Phase 14 (config governance); strengthens compliance/audit narrative

---

## Background

The USAA VPP underwriting rules engine (`lib/underwriting.py`) is pure Python — deterministic,
zero-LLM, fully unit-tested. It makes decisions based on two layers:

**Layer 1 — Rule logic** (the decision structure):
```python
def classify_risk(declared_value, storage):
    if declared_value > 25_000: return "high"
    if storage == "daily_wear" and declared_value > 2_500: return "high"
    ...
```
This is engineering and SME work. The shape of the decision tree changes rarely and belongs in
code.

**Layer 2 — Rule configuration** (the numbers inside that logic):
```python
STORAGE_RATES   = { "bank_vault": 0.005, "home_safe": 0.010, "standard": 0.015, "daily_wear": 0.020 }
CATEGORIES      = { "jewelry": CategoryConfig(high_value_threshold=2_500, gia_required_above=5_000, ...) }
_SCHEDULED_THRESHOLD         = 10_000.0
_MANUAL_REVIEW_THRESHOLD     = 25_000.0
_APPRAISAL_MAX_AGE_DAYS      = 730
_MIN_USD_PER_CARAT           = 500.0
_MAX_USD_PER_CARAT           = 250_000.0
```

These are **actuarial and business parameters** — the numbers an underwriting manager or actuary
adjusts when market conditions change, regulatory requirements shift, or new product lines launch.

**The problem:** all 18 thresholds are Python constants with no audit trail, no approval
workflow, no change history, and no way for a non-technical stakeholder to inspect or propose
changes. When `bank_vault` rate changes from 0.5% → 0.4%, a developer edits a file, deploys, and
nobody knows it happened.

---

## The insight

Rule parameters have the same lifecycle as editorial content — they are drafted, reviewed,
approved, published, and audited. CMS concepts map naturally:

| CMS concept      | Rules meaning                                                               |
|------------------|-----------------------------------------------------------------------------|
| Block type       | A configuration object (`StorageRates`, `CategoryThresholds`, `GlobalLimits`) |
| Document         | The current authoritative value of that configuration                       |
| Draft            | Proposed rate change — staged, not yet active                               |
| Published        | Active in production, enforced by the rules engine                          |
| Version history  | "May 1: bank_vault rate 0.5% → 0.4% — approved by J. Smith, actuary"       |
| Webhook on publish | Triggers rules engine reload + automated regression test run              |

---

## The new primitive: singleton documents

Unlike intake forms (many instances of one block type), configuration objects have exactly one
authoritative instance. This requires a new Astraeus concept not currently in the design:

```python
@cms.block("storage_rates", singleton=True)
class StorageRates:
    """Annual premium rates by storage location. Actuarial team owns this."""
    bank_vault: NumberField(label="Bank Vault Rate",  default=0.005, precision=4,
                            help_text="0.50% — climate-controlled, 24hr security")
    home_safe:  NumberField(label="Home Safe Rate",   default=0.010, precision=4,
                            help_text="1.00% — UL-rated safe, fixed to structure")
    standard:   NumberField(label="Standard Rate",    default=0.015, precision=4,
                            help_text="1.50% — drawer, shelf, unlocked cabinet")
    daily_wear: NumberField(label="Daily Wear Rate",  default=0.020, precision=4,
                            help_text="2.00% — worn or carried regularly")
```

`singleton=True` means:
- Only one published document of this type exists at any time
- `cms.documents.get_singleton("storage_rates")` always returns it
- The admin UI shows a "Settings"-style form instead of a document list
- Publishing a new version archives the previous one (still queryable for audit)

---

## Configuration objects in the rules engine

Five blocks cover the full surface of `lib/underwriting.py`:

### 1. `StorageRates`
```python
@cms.block("storage_rates", singleton=True)
class StorageRates:
    bank_vault: NumberField(label="Bank Vault Rate",  precision=4, default=0.005)
    home_safe:  NumberField(label="Home Safe Rate",   precision=4, default=0.010)
    standard:   NumberField(label="Standard Rate",    precision=4, default=0.015)
    daily_wear: NumberField(label="Daily Wear Rate",  precision=4, default=0.020)
```

### 2. `GlobalThresholds`
```python
@cms.block("global_thresholds", singleton=True)
class GlobalThresholds:
    scheduled_threshold:            NumberField(label="Blanket → Scheduled ($)",          default=10_000)
    manual_review_threshold:        NumberField(label="Auto-approve Ceiling ($)",          default=25_000)
    appraisal_max_age_standard:     NumberField(label="Appraisal Max Age — Standard (days)", default=730)
    appraisal_max_age_high_value:   NumberField(label="Appraisal Max Age — High Value (days)", default=365)
    appraisal_high_value_threshold: NumberField(label="Appraisal High-Value Floor ($)",   default=10_000)
    min_usd_per_carat:              NumberField(label="Min USD/ct (Reasonableness)",       default=500)
    max_usd_per_carat:              NumberField(label="Max USD/ct (Reasonableness)",       default=250_000)
```

### 3. `CategoryConfig` (one block, keyed by category)
```python
@cms.block("category_config")
class CategoryConfig:
    category:              SelectField(label="Category", choices=["jewelry","bikes","cameras","guns_bows","instruments","watches"])
    high_value_threshold:  NumberField(label="High-Value Threshold ($)")
    gia_required_above:    NumberField(label="GIA Required Above ($)", required=False)
    photo_slots:           ListField(item_type=TextField(), label="Photo Slot Labels")
```
Six documents — one per category. Not singletons; each is an independently publishable record.

### 4. `RiskMatrix` (the hierarchical risk rules)
```python
@cms.block("risk_rule")
class RiskRule:
    priority:         NumberField(label="Priority (lower = evaluated first)")
    risk_level:       SelectField(label="Risk Level", choices=["low","medium","high"])
    min_value:        NumberField(label="Min Declared Value ($)", required=False)
    storage:          SelectField(label="Storage Location (leave blank for any)", required=False, ...)
    description:      TextField(label="Human description of this rule")
```
Ordered list of rules evaluated first-match-wins. Adding a new rule is a CMS edit + publish,
not a code change.

---

## How the rules engine consumes governed config

The rule *logic* is unchanged. Only the source of the parameters moves:

```python
# lib/underwriting.py — before
STORAGE_RATES = { "bank_vault": 0.005, "home_safe": 0.010, ... }   # hardcoded

def calculate_premium(declared_value: float, storage: str) -> float:
    rate = STORAGE_RATES[storage]
    return round(declared_value * rate, 2)
```

```python
# lib/underwriting.py — after
async def get_storage_rates() -> dict:
    doc = await cms.documents.get_singleton("storage_rates")
    return doc.data   # same shape, now governed

async def calculate_premium(declared_value: float, storage: str) -> float:
    rates = await get_storage_rates()
    return round(declared_value * rates[storage], 2)
```

The rules engine caches the singleton at boot and reloads on webhook signal — one cache
invalidation, not a deploy.

---

## The approval + reload loop

```
Actuary drafts a rate change in the admin UI
         │
         ▼
Underwriting manager reviews the diff (v12 → v13)
         │
         ▼
Manager clicks Publish
         │
         ▼
Webhook fires → rules engine invalidates cache
         │
         ▼
Regression test suite runs automatically against new config
  (tests/data/rules_matrix/*.json — all 6 categories)
         │
         ├─ PASS → new rates active for next submission
         └─ FAIL → alert raised, previous config remains active
                   (version v12 still published; v13 in "failed" state)
```

The regression test integration is the key detail — it closes the loop between "governance tool"
and "safe deployment." The webhook payload carries the new config version; the test runner
compares expected decisions in the matrix against decisions computed with the new config.

---

## What USAA sees in the admin UI

Two tabs alongside the intake form schema manager (from the intake POC):

**"Item Schemas"** — block type definitions, field versions, migration log  
**"Underwriting Rules"** — four settings panels:

1. **Storage Rates** — rate inputs per location, diff against previous version on hover
2. **Global Thresholds** — scheduled threshold, manual review ceiling, appraisal age limits
3. **Category Settings** — per-category card: high-value threshold, GIA requirement, photo slots
4. **Risk Rules** — ordered list of classification rules, drag-to-reorder, priority numbers

Each panel shows: current published values, draft (if any), and a version history sidebar with
"who changed what, when, and why" (the `versionMessage` field on every publish).

---

## Demo extension (adds to the 20-minute intake form demo)

**5 minutes, appended to the intake form demo:**

1. **"Here are the rate tables"** — open Storage Rates panel. "This is what drives every premium
   calculation. Actuarially derived, stored in the same system as your item schemas."

2. **"Watch a rate change"** — live: change `bank_vault` from 0.50% → 0.45%, add version message
   "Q3 actuary review — vault penetration rate declined." Click Publish.

3. **"The audit trail"** — version history shows: previous value, new value, timestamp, author,
   version message. "Every regulatory audit question about 'what rates were active on date X' is
   answered by this panel."

4. **"The safety net"** — "When you publish a rule change, the regression suite runs
   automatically. If it breaks an expected decision, the publish rolls back. You can't
   accidentally break underwriting logic through the UI."

---

## Build breakdown

**In `starlette-cms` (new capabilities):**
- `singleton=True` parameter on `@cms.block()` / `@block()`
- `cms.documents.get_singleton(block_type)` — always returns the current published document
- Singleton publish semantics — archives previous, no "multiple published" state
- `NumberField(precision=n)` — needed for rate display (already identified in intake POC)
- `versionMessage` on publish (may already exist — check document API)

**In `usaa-vpp` (~150 lines):**
- `usaa_vpp/cms/config_blocks.py` — 4 config block definitions
- `usaa_vpp/cms/seed.py` — seeds initial published config from current hardcoded constants
- Modified `lib/underwriting.py` — reads from CMS instead of constants (cache + reload)
- Webhook handler — invalidates cache, triggers regression run

**In `dev-gui` (minimal):**
- Settings panels consume the same schema API — no new components, just new block types
- starlette-editor Phase 2 delivers the real admin UI; dev-gui panels are placeholder

---

## Learning goals

| Question | How the POC answers it |
|---|---|
| Do singleton documents cover the "one authoritative config" pattern? | Seed and read-back reveals edge cases |
| Does cache-on-boot + webhook-invalidation feel right for a rules engine? | Integration with the real workflow answers this |
| What's the DX for seeding initial config from existing constants? | Writing seed.py surfaces friction |
| Does the approval workflow (draft → publish → rollback) satisfy compliance intuitions? | USAA feedback answers this directly |
| Should risk rules (the ordered match table) be documents too, or just parameters? | Writing the RiskRule block reveals whether it's worth the complexity |

---

## Roadmap implications

| POC output | Astraeus impact |
|---|---|
| `singleton=True` block + `get_singleton()` | **Phase 4/5** — new document pattern |
| `NumberField(precision=n)` | **Phase 4** — field type (also in intake POC) |
| Singleton publish semantics + version archive | Document API extension |
| Governed config as third document use case (alongside editorial + intake) | Broadens positioning from "headless CMS" to "governed data platform" |
| Compliance/audit narrative with version history | Changes README framing |
| Webhook → test-suite integration pattern | Architecture documentation |

---

## Relationship to the intake form POC

These two POCs compose naturally and should be demoed together:

```
Item Schemas (intake POC)          Rule Configuration (this POC)
──────────────────────────         ──────────────────────────────────
Many documents per block type      One canonical document per block type
Field definitions evolve slowly    Threshold values change on actuary cycle
Schema migration + backfill        Publish → cache invalidate → test run
SME: underwriting field team       SME: actuarial / compliance team
```

Both use the same CMS primitives. Both are governed via the same admin UI. The only difference
is cardinality and the downstream effect of a publish.

---

## New ADR needed

The singleton document pattern is a meaningful architectural decision with tradeoffs worth
recording — see `docs/decisions/009-singleton-documents.md`.
