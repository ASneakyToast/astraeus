# Use Case: Test Case Library (USAA VPP Scenario & Preset Management)

**Status:** POC planned  
**Explored:** 2026-06-13  
**Related:** [`vpp-underwriting-intake.md`](./vpp-underwriting-intake.md), [`vpp-rule-governance.md`](./vpp-rule-governance.md), [`vpp-eval-dataset.md`](./vpp-eval-dataset.md)  
**Packages:** `starlette-cms` (core)  
**Roadmap impact:** Introduces authored fixtures as a document type; establishes pattern for institutional knowledge preservation; connects to CI/CD via webhook-triggered test runs

---

## Background

USAA VPP has two parallel collections of curated test cases that represent the same underlying
intent — "here is an item we know the correct answer for" — but live in disconnected places:

**Dev-GUI presets** (`dev-gui/front-end/src/pages/UnderwritePage.tsx`, lines 80–161):
```typescript
const PRESETS = [
  {
    label: '1ct Diamond Solitaire',
    category: 'jewelry',
    declaredValue: 8000,
    storage: 'home_safe',
    itemDescription: '1.0ct round brilliant diamond solitaire ring, 14k white gold, GIA certified',
    itemSpecs: { carat: 1.0, colorGrade: 'G', clarityGrade: 'VS1', metalType: '14K White Gold' },
    expectedStatus: 'auto_approved',
    expectedRisk: 'low',
    expectedPremium: 80,
    photoUrls: ['/api/assets/replicate-prediction-p12y0jnte9rmw0cypfj8c7s28c.jpeg', '', ''],
  },
  // ... 6 more
]
```

**Regression scenarios** (`tests/data/rules_matrix/*.json`, `tests/scenarios/`):
```json
{
  "id": "jewelry-high-value-gia-required",
  "form_data": { "declared_value": 12000, "storage_location": "home_safe", "category": "jewelry", ... },
  "appraisal_data": { "present": true, "data": { "appraisal_date": "2023-01-01", ... } },
  "expected_uw_decision": { "uw_status": "manual_review", "risk_level": "high", ... }
}
```

These are the same concept — curated inputs with expected outputs — scattered across TypeScript,
Python, and JSON with no shared authorship, no rationale, and no change history.

When the underwriting team encounters a tricky real-world claim — a diamond with a suspiciously
low declared value that exposed a gap in the rules — that institutional knowledge exists only in
someone's memory or a Slack thread. It is never encoded into the test suite in a governed way.

---

## The insight: test cases are authored content

A test case is not infrastructure — it is a document that encodes institutional knowledge about
correct system behavior. It was authored by someone, for a reason, at a point in time. That
provenance matters:

- Who added this scenario?
- Why? Was it a real claim that exposed a gap?
- What rule version was it written for?
- When the rules change, does the expected outcome change too?
- Is this scenario still valid, or has the product changed around it?

These questions are unanswerable when test cases live as hardcoded constants. As CMS documents,
they are first-class governed artifacts.

---

## Block definition

```python
@cms.block("test_scenario")
class TestScenario:
    """A curated test case encoding correct system behavior for a known input."""

    label:        TextField(label="Scenario Name",
                            help_text="Short, human-readable. E.g. '1ct Diamond Solitaire — GIA present'")
    category:     SelectField(label="Category",
                              choices=["jewelry","bikes","cameras","guns_bows","instruments","watches"])
    rationale:    TextField(label="Why this scenario exists",
                            help_text="What edge case, incident, or product decision does this encode?")

    # Input
    form_data:     JSONField(label="Form Data (UnderwriteRequest shape)")
    appraisal_data: JSONField(label="Appraisal Data", required=False)
    gia_data:       JSONField(label="GIA Data",        required=False)

    # Expected outputs
    expected_uw_status:    SelectField(choices=["auto_approved","manual_review"],
                                       label="Expected Decision")
    expected_risk_level:   SelectField(choices=["low","medium","high"],
                                       label="Expected Risk Level")
    expected_premium:      NumberField(label="Expected Premium ($)", required=False)
    expected_flags:        ListField(item_type=TextField(), label="Expected Flags", required=False)

    # Governance metadata
    rule_config_ref:  DocumentRef(block_type="global_thresholds",
                                  label="Rule Config This Scenario Was Written For")
    source:           SelectField(label="Source",
                                  choices=["authored","derived_from_real_claim","ai_generated","migrated"])
    active:           BoolField(label="Active (include in CI runs)", default=True)
```

`JSONField` is a new field type — for structured blobs that don't warrant their own block
definition but need to be stored and queried. Also needed by the eval dataset and prompt
versioning use cases.

---

## How this replaces the current split

| Current location | Migrated to CMS | Benefit |
|---|---|---|
| `UnderwritePage.tsx` PRESETS array | `test_scenario` documents tagged `source="authored"` | Dev-GUI fetches presets from the schema API; no hardcoding |
| `tests/data/rules_matrix/*.json` | `test_scenario` documents tagged `source="migrated"` | Single source of truth for CI and dev-GUI |
| `tests/scenarios/` bundles | `test_scenario` documents tagged `source="migrated"` | Same |
| "This claim from March exposed a gap" (Slack) | `test_scenario` document with `rationale` and `source="derived_from_real_claim"` | Institutional knowledge preserved |

Migration is a one-time seed script — JSON files become documents, each tagged with source and
linked to the rule config version active at time of migration.

---

## The CI integration

When a rule config change is proposed for publish, CI runs the test scenario suite against it
automatically via webhook. Each scenario is an API call to `apply_rules()` with the proposed
config:

```python
# ci/run_scenarios.py

async def run_against_config(proposed_config: dict) -> ScenarioReport:
    scenarios = await cms.documents.list("test_scenario",
                                         filters={"active": True},
                                         limit=500)
    results = []
    for s in scenarios:
        actual = apply_rules(s.data["form_data"], s.data.get("appraisal_data"), config=proposed_config)
        expected = s.data["expected_uw_status"]
        passed = actual.uw_status == expected
        results.append(ScenarioResult(id=s.id, label=s.data["label"], passed=passed,
                                       actual=actual.uw_status, expected=expected))

    return ScenarioReport(
        total=len(results),
        passed=sum(r.passed for r in results),
        failed=[r for r in results if not r.passed],
    )
```

The webhook payload from publishing a rule config draft triggers this run. If any scenario
fails, the publish is blocked and the actuary sees a diff: "Scenario '1ct Diamond Solitaire'
expected auto_approved, got manual_review under proposed v13."

---

## The scenario authoring workflow

Non-technical SMEs can add scenarios via the admin UI:

1. SME encounters a real claim that exposed an edge case — e.g., "we got a $15,000 watch claimed
   with a home_safe, no appraisal. The system auto-approved it but our actuary flagged it."
2. SME opens the scenario editor: fills in form_data, sets `expected_uw_status: manual_review`,
   writes rationale: "Watch >$10k in home_safe without appraisal should require manual review.
   See claim #VPP-2024-0391."
3. SME links to the current rule config version (auto-populated)
4. SME saves as draft, underwriting manager reviews, publishes
5. Scenario is now in the CI suite for every future rule change

This is institutional knowledge preservation with a review gate — not just a test file added in
a PR that nobody reads.

---

## The dev-GUI connection

The 7 hardcoded TypeScript presets are replaced:

```typescript
// Before — hardcoded in UnderwritePage.tsx:
const PRESETS = [ { label: '1ct Diamond Solitaire', ... }, ... ]

// After — schema-driven:
const presets = await fetch('/cms/api/documents/test_scenario?active=true')
  .then(r => r.json())
```

The dev-GUI now reflects the governed test case library in real time. When an SME adds a new
scenario, it appears in the dev-GUI preset picker on next load. No code change required.

---

## Build breakdown

**In `starlette-cms` (new capabilities):**
- `JSONField` — structured blob storage, validated as JSON on write
- Scenario-to-rule-config relationship via `DocumentRef` (shared with eval dataset)
- `documents.list()` filter support (`active: True`, `category: "jewelry"`)

**In `usaa-vpp` (~100 lines):**
- `usaa_vpp/cms/scenario_blocks.py` — TestScenario block definition
- `usaa_vpp/cms/seed_scenarios.py` — one-time migration of existing JSON + TypeScript presets
- `ci/run_scenarios.py` — webhook-triggered CI runner (replaces `run_uw_test.py`)

**In `dev-gui` React (~50 lines changed):**
- Replace `PRESETS` constant with `useDocumentList("test_scenario", { active: true })` hook
- Preset picker renders from CMS documents instead of hardcoded array

---

## Learning goals

| Question | How the POC answers it |
|---|---|
| Does `JSONField` provide enough structure for scenario input data, or do we need nested blocks? | Writing the seed migration reveals the shape of real inputs |
| How does the scenario authoring UX feel for a non-technical SME? | USAA demo feedback |
| Is the rule-config link (`rule_config_ref`) actually used, or just noise? | After 3 months of use, are these refs ever queried? |
| Does merging the dev-GUI preset source with the CI test source cause friction? | Are there scenarios valid for demos but not CI, or vice versa? (The `active` flag handles this) |

---

## Roadmap implications

| POC output | Astraeus impact |
|---|---|
| `JSONField` | **Phase 4** — new field type; broadly useful |
| Authored fixtures as document type | New use case documentation |
| Webhook-triggered CI pattern | Architecture documentation + example |
| `documents.list()` filter API | Document API hardening |
| Institutional knowledge preservation narrative | Adds depth to "governed data platform" positioning |
