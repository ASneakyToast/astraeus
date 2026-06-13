# Use Case: Eval Dataset (USAA VPP Human-Scored Runs)

**Status:** POC planned  
**Explored:** 2026-06-13  
**Related:** [`vpp-underwriting-intake.md`](./vpp-underwriting-intake.md), [`vpp-rule-governance.md`](./vpp-rule-governance.md), [`vpp-test-case-library.md`](./vpp-test-case-library.md), [`vpp-prompt-versioning.md`](./vpp-prompt-versioning.md)  
**Packages:** `starlette-cms` (core)  
**Roadmap impact:** Introduces document references / relationships (ADR 010); completes the governed feedback loop; positions Astraeus as a governed AI evaluation layer

---

## Background

The dev-gui has a "Score this run" button. After the underwriting workflow completes, a reviewer
can rate the quality of the AI pipeline's output and leave notes. These scores are saved as eval
entries — the raw material for measuring whether the system is improving or regressing.

Currently those entries are ephemeral or lightly persisted with no governance:
- No authorship (who scored it?)
- No link to the rule version active at score time
- No link to the prompt versions active at score time
- No way to query "how many runs would change decision if we publish this rule update?"
- No audit trail of evaluation decisions

An eval entry is not just a score — it is a **governed judgment** that links a submission, a
human decision, and a system configuration at a point in time. It is the feedback signal that
makes every other governed artifact meaningful.

---

## The insight: eval entries close the feedback loop

The three governed artifact types from the other use cases only matter if you can measure their
effect. The eval dataset is what makes measurement possible:

```
Governed Config (rule params, v12)
        │
        ▼
Intake Submission (jewelry item, doc_01j...)
        │
        ▼
Workflow Output (auto_approved, $80 premium, 0 flags)
        │
        ▼
Human Score (reviewer: "correct — well within GIA-verified range, 5/5")
        │
        ▼
Eval Entry (submission_ref, rule_version=12, prompt_versions={...}, score=5, notes="...")
        │
        ▼
Query: "publish rule v13 (bank_vault 0.5%→0.4%) — what changes across 500 scored runs?"
```

This is the loop that doesn't exist today. Without it, every rule change and every prompt change
is a leap of faith.

---

## The new primitive: document references

An eval entry cannot be modeled as a standalone document — it is intrinsically relational. It
references:

- A **submission document** (the intake record being evaluated)
- A **rule config version** (which thresholds were active at run time)
- One or more **prompt versions** (which AI step prompts were active)
- The **workflow output** (the actual decision and flags produced)

This requires a new Astraeus concept: **document references** — typed foreign keys between
documents, resolved lazily and queryable.

```python
@cms.block("eval_entry")
class EvalEntry:
    """A human-scored evaluation of one underwriting workflow run."""

    # References to other governed artifacts
    submission_ref:     DocumentRef(block_type="jewelry_item",   label="Submission")
    rule_config_ref:    DocumentRef(block_type="global_thresholds", label="Rule Config Version")
    prompt_refs:        ListField(item_type=DocumentRef(block_type="uw_prompt"), label="Active Prompts")

    # The workflow output at score time (snapshot, not live reference)
    uw_status:          SelectField(choices=["auto_approved", "manual_review"], label="Decision")
    annual_premium:     NumberField(label="Annual Premium ($)", required=False)
    uw_flags:           ListField(item_type=TextField(), label="Flags")

    # Human judgment
    score:              SelectField(choices=["1","2","3","4","5"], label="Quality Score (1–5)")
    correct_decision:   SelectField(choices=["yes","no","borderline"], label="Was the decision correct?")
    notes:              TextField(label="Reviewer Notes", required=False)
    reviewer:           TextField(label="Reviewer", required=False)
```

`DocumentRef` is the new primitive — a typed pointer to another document that the framework can
resolve, validate at write time, and traverse at query time.

---

## The feedback query

The most important capability the eval dataset unlocks is **counterfactual analysis** on proposed
config changes. Before publishing rule v13, the question becomes answerable:

```python
# "If we publish this rate change, what flips?"
async def preview_rule_change(proposed_config: dict) -> ChangePreview:
    eval_entries = await cms.documents.list("eval_entry", limit=500)

    changes = []
    for entry in eval_entries:
        submission = await entry.submission_ref.resolve()
        old_decision = apply_rules(submission.data, config=entry.rule_config_ref.data)
        new_decision = apply_rules(submission.data, config=proposed_config)

        if old_decision.uw_status != new_decision.uw_status:
            changes.append({
                "submission_id": submission.id,
                "was":  old_decision.uw_status,
                "now":  new_decision.uw_status,
                "score": entry.score,
                "reviewer_notes": entry.notes,
            })

    return ChangePreview(
        total_evaluated=len(eval_entries),
        decisions_flipped=len(changes),
        flip_details=changes,
    )
```

This surfaces as a diff panel in the admin UI when an actuary reviews a proposed rule change:
"Publishing this change would flip 12 of 500 scored submissions from auto_approved to
manual_review. 9 of those 12 were scored 5/5 (correct auto-approval) — review before
proceeding."

That is the difference between a governed system and a system with governance theater.

---

## Connecting to the regression test suite

The existing regression matrix (`tests/data/rules_matrix/*.json`) is a manually authored dataset
of expected inputs and outputs. The eval dataset is the live, human-scored complement to it.

The connection:

```
Scenario Library (authored test cases, static)     ← vpp-test-case-library.md
        +
Eval Dataset (real runs, human-scored, growing)    ← this document
        =
Full validation surface for any change to rules, prompts, or schemas
```

When a rule config change is proposed for publish, both surfaces run:
1. All scenario library cases must still produce expected outcomes
2. The eval dataset preview shows the real-world distribution of flips

Neither alone is sufficient — the scenario library tests edge cases, the eval dataset tests
the actual distribution of real submissions.

---

## What USAA sees in the admin UI

A new **"Evaluations"** section alongside Item Schemas and Underwriting Rules:

1. **Eval feed** — chronological list of scored runs. Filter by: scorer, date range, rule version,
   score value, decision flipped (yes/no). Click any entry to see full submission detail
   alongside the human score and notes.

2. **Rule change preview** — when an actuary is reviewing a draft rule config, a panel shows:
   "X of Y scored submissions would change decision under this config." Expandable diff per flip.

3. **Score distribution** — aggregate view: score histogram, accuracy rate, most common flags
   on low-scored runs, trend line over time. Answers: "is the system getting better?"

4. **Coverage gap detector** — "These 23 submissions have never been scored. These 8 have only
   one score. High-value items are underrepresented in the eval dataset." Guides where to
   invest review time.

---

## Build breakdown

**In `starlette-cms` (new capabilities):**
- `DocumentRef(block_type)` — typed reference field; validates target exists on write; lazy resolution
- `cms.documents.list()` with `resolve_refs=True` option — bulk resolution without N+1 queries
- Reference integrity on delete (configurable: block delete, cascade, or nullify)
- This deserves its own ADR: **ADR 010 — Document references**

**In `usaa-vpp` (~100 lines):**
- `usaa_vpp/cms/eval_blocks.py` — EvalEntry block definition
- Modified dev-gui "Score this run" flow — creates EvalEntry document with all refs populated
- `GET /api/eval/preview-rule-change` — runs counterfactual analysis against eval dataset

**In `dev-gui` React (~150 lines):**
- Evaluations feed view (reuses SchemaForm + document list patterns from intake POC)
- Rule change preview panel in the governance UI
- Score distribution charts (simple, no new dependencies)

---

## Learning goals

| Question | How the POC answers it |
|---|---|
| Is `DocumentRef` the right abstraction, or do we need foreign keys at the DB layer? | Writing EvalEntry and resolving refs reveals the tradeoffs |
| Does the counterfactual query perform acceptably at 500 entries? | Real data answers this |
| What does reference integrity feel like when a submission is deleted? | Edge cases surface during integration |
| Does the feedback loop actually change how USAA teams think about rule changes? | Demo feedback answers this |
| Is the eval dataset worth governing as CMS content, or is a plain database table enough? | If governance features (version history, authorship, audit) are never used, reconsider |

---

## Roadmap implications

| POC output | Astraeus impact |
|---|---|
| `DocumentRef` field type | **Phase 5** — relationship primitive; unlocks a class of use cases |
| Reference resolution API (`resolve_refs=True`) | Document API extension |
| Counterfactual query pattern | Architecture documentation + example |
| Eval dataset as governed artifact | Positions Astraeus as AI evaluation infrastructure |
| Feedback loop closing the governed data cycle | Core narrative for "governed data platform" positioning |

---

## The complete governed data cycle

With all four USAA-VPP use cases together, Astraeus covers the full lifecycle of a governed AI
system — not just a piece of it:

```
Item Schemas          — what data gets collected
        ↓
Rule Configuration    — how decisions get made
        ↓
Eval Dataset          — whether decisions are correct
        ↑_____________________________________________
  "publish this rule change? here's what flips
   across 500 human-scored real submissions"

        +

Test Case Library     — edge cases and institutional knowledge
Prompt Versioning     — AI behavior governance
```

This is the story that changes how Astraeus is described. It is not a headless CMS for Joel's
personal site that also happens to work for insurance companies. It is a governed data platform
for systems where the data, the rules, and the AI behavior all need audit trails.
