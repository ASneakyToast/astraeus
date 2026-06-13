# Use Case: Prompt Versioning (USAA VPP AI Pipeline Governance)

**Status:** POC planned  
**Explored:** 2026-06-13  
**Related:** [`vpp-rule-governance.md`](./vpp-rule-governance.md), [`vpp-eval-dataset.md`](./vpp-eval-dataset.md), [`vpp-test-case-library.md`](./vpp-test-case-library.md)  
**Packages:** `starlette-cms` (core)  
**Roadmap impact:** Extends singleton pattern to AI behavior governance; positions Astraeus for production AI system use cases; introduces prompt-as-content framing

---

## Background

The USAA VPP AI pipeline has five distinct steps, each driven by prompts embedded in Pkl workflow
files:

| Step | File | What the prompt governs |
|---|---|---|
| Intake | `workflows/vpp_intake.pkl` | Document classification, field extraction from appraisal/GIA |
| Fraud detection | `workflows/vision_dox.pkl` | Per-photo risk assessment, AI generation likelihood |
| Pricing | `workflows/pricing_test.pkl` | Market-based pricing research and estimation |
| Consistency audit | `workflows/uw_consistency.pkl` | Cross-source consistency scoring |
| Orchestration | `workflows/underwriting.pkl` | Final report assembly |

Each prompt encodes significant domain expertise — what fields to extract, how to classify
ambiguous photos, what counts as a consistency violation, how to calibrate confidence scores.
These prompts are not boilerplate; they represent weeks of prompt engineering work that directly
affects underwriting accuracy.

**The problem:** prompts live in Pkl files, versioned only by git, with no:
- Audit trail of who changed what and why
- Way for a domain expert (underwriting manager, fraud analyst) to propose a change without
  writing code
- Mechanism to test a prompt change against historical data before deploying
- Record of which prompt version was active when a specific submission was evaluated
- Ability to roll back a prompt change without a git revert and redeploy

This is the same governance gap as the rules engine — except the consequences of an unaudited
prompt change are less deterministic and therefore harder to detect.

---

## The insight: prompts are singleton governed config

A production prompt is not fundamentally different from a storage rate table. It is an artifact
that:
- Has exactly one authoritative published version at any time
- Changes infrequently but consequentially when it does
- Should require review before going live
- Needs an audit trail for compliance and debugging
- Directly affects outputs that are evaluated by the eval dataset

The singleton document pattern from `vpp-rule-governance.md` applies directly. Each prompt is a
singleton block — one published document, full version history, webhook on publish.

---

## Block definition

```python
@cms.block("uw_prompt", singleton=True)
class UwPrompt:
    """A versioned prompt for one step of the underwriting AI pipeline."""

    step:         SelectField(
                      label="Pipeline Step",
                      choices=["intake", "fraud_detection", "pricing", "consistency", "orchestration"]
                  )
    system:       TextField(label="System Prompt",  required=False,
                             help_text="The system message sent to the model")
    user_template: TextField(label="User Prompt Template",
                              help_text="Jinja2 template — use {{ variable }} for runtime substitution")
    model:        TextField(label="Model ID",
                             help_text="e.g. riky-vibe, claude-opus-4-8")
    temperature:  NumberField(label="Temperature",   default=0.0, precision=2)
    max_tokens:   NumberField(label="Max Tokens",    default=4096)

    # Governance metadata
    change_rationale: TextField(
        label="What changed and why",
        help_text="Required on publish. E.g. 'Added hallmark detection instruction after 3 false negatives on vintage jewelry'"
    )
    authored_by:  TextField(label="Domain expert who authored this version", required=False)
```

One document per pipeline step — five singletons total. Because `step` is a `SelectField` and
this is `singleton=True`, the registry enforces: at most one published document per
`(block_type, step)` combination. (This is a parameterized singleton — a small extension to
the base singleton concept from ADR 009.)

---

## How the pipeline consumes governed prompts

The Pkl workflow files currently embed prompts inline. After the POC they fetch the published
document at workflow boot time:

```python
# lib/prompt_loader.py (new)

_cache: dict[str, UwPromptDoc] = {}

async def get_prompt(step: str) -> UwPromptDoc:
    if step not in _cache:
        _cache[step] = await cms.documents.get_singleton("uw_prompt", filters={"step": step})
    return _cache[step]

async def invalidate(step: str | None = None) -> None:
    if step:
        _cache.pop(step, None)
    else:
        _cache.clear()
```

The webhook handler calls `invalidate()` when a prompt is published — same pattern as the rules
engine cache invalidation.

In the Pkl workflow, the prompt step becomes:

```pkl
# Before — prompt hardcoded in Pkl:
["run_intake"] {
  instruction = """
    You are an insurance document specialist. Extract the following fields...
    [200 lines of carefully engineered prompt]
  """
}

# After — prompt loaded from CMS at runtime:
["run_intake"] {
  instruction = "{{inputs.intake_prompt}}"   // injected by workflow runner from CMS
}
```

The workflow runner calls `get_prompt("intake")` before starting and injects it as a template
variable. The Pkl file becomes a structural definition; the prompt content is governed elsewhere.

---

## The eval dataset connection

Because each EvalEntry document records `prompt_refs` (the prompt versions active at evaluation
time), the eval dataset becomes a full accounting of system configuration at any point:

```
EvalEntry {
  submission_ref:   → jewelry_item / doc_01j...
  rule_config_ref:  → global_thresholds / v12
  prompt_refs:      → [intake/v8, fraud_detection/v3, consistency/v5]
  score: 4
  notes: "Correct decision, but consistency score seemed low for clean GIA cert"
}
```

This makes attribution possible: "Our consistency scores dropped in March. What changed?" The
eval dataset shows that `consistency/v6` was published on March 14. Diff v5 → v6 shows the
change. Roll back to v5 and rescore — if scores recover, the prompt change was the cause.

Without versioned prompts stored alongside eval entries, this attribution is impossible.

---

## The prompt change workflow

```
Fraud analyst notices pattern: AI is flagging vintage hallmarks as suspicious
        │
        ▼
Opens prompt editor for "fraud_detection" step in admin UI
Shows current published version (v3) alongside draft editor
        │
        ▼
Adds instruction: "Antique and vintage hallmarks (pre-1980) differ
in appearance from modern stamps. Do not flag aged patina or
non-standard vintage markings as suspicious without additional indicators."
Fills in change_rationale field
        │
        ▼
Saves as draft — visible only to admins
        │
        ▼
Underwriting manager reviews the diff (v3 → v4)
Runs the test scenario suite against v4 (webhook-triggered)
        │
        ├─ All scenarios pass → manager clicks Publish
        │         │
        │         ▼
        │   Webhook fires → workflow runner cache invalidates
        │   Next run uses v4
        │   EvalEntry records prompt_refs including fraud_detection/v4
        │
        └─ Scenario fails → manager sees: "Scenario 'Vintage Brooch — Hallmark Present'
                            expected fraud risk LOW, got MEDIUM under proposed v4"
                            Draft remains, analyst revises
```

---

## What USAA sees in the admin UI

A **"Pipeline Prompts"** section with five cards — one per step:

Each card shows:
- Current published version number and publish date
- Author and change rationale from the last publish
- "Edit draft" button (opens a split-pane: current published | draft editor)
- Version history sidebar: every past version, diff-able against any other

When viewing a draft before publishing:
- Side-by-side diff of current vs. proposed prompt text
- "Run test scenarios" button — triggers the webhook-driven CI run
- Scenario results inline: pass/fail per scenario, failures highlighted
- "Publish" button disabled until at least one test run passes

---

## Build breakdown

**In `starlette-cms` (small extension to singleton pattern):**
- Parameterized singleton: `singleton=True` + a discriminator field (`step`) means one published
  doc per `(block_type, discriminator_value)` — see ADR 009 extension note
- `cms.documents.get_singleton(block_type, filters={"step": "intake"})` — filter-qualified
  singleton lookup (already implied by ADR 009 implementation notes)

**In `usaa-vpp` (~80 lines):**
- `usaa_vpp/cms/prompt_blocks.py` — UwPrompt block definition
- `lib/prompt_loader.py` — cached singleton loader with webhook invalidation
- `usaa_vpp/cms/seed_prompts.py` — one-time migration: extract prompts from Pkl files into
  initial published documents
- Modified workflow runner — injects prompts from CMS as template variables

**In `dev-gui` React (minimal):**
- Prompt editor is a starlette-editor Phase 2 concern — the POC just validates the data model
- The eval feed already shows prompt_refs; clicking through resolves to the prompt version detail

---

## The unique challenge: prompt extraction from Pkl

The seed migration requires extracting prompts from the existing Pkl workflow files. These files
interleave structure and prompt text. The extraction is one-time and manual — identify the
instruction strings, paste into CMS, verify the workflow still produces the same outputs.

This is actually a useful forcing function: it requires reading every prompt carefully, writing a
`change_rationale` for the initial version ("migrated from vpp_intake.pkl — original author:
workflow team"), and confirming that the injected-prompt path produces identical outputs to the
inline-prompt path. That validation is exactly the kind of regression check the system needs.

---

## Learning goals

| Question | How the POC answers it |
|---|---|
| Does the Pkl injection pattern (`{{inputs.intake_prompt}}`) work cleanly? | Integration test against real workflow run |
| Is the latency of CMS prompt lookup acceptable at workflow boot time? | Cache-on-boot means effectively zero latency; measure cache miss time |
| Do domain experts actually use the prompt editor, or does it feel too technical? | USAA demo feedback — prompt text is still complex even with a nice UI |
| Is a parameterized singleton the right model, or should each step be its own block type? | Writing five prompt documents reveals whether `step` as discriminator creates confusion |
| Does the eval attribution ("prompt v4 caused score drop") actually surface in practice? | Requires 2–3 months of eval data accumulation before the signal is visible |

---

## Roadmap implications

| POC output | Astraeus impact |
|---|---|
| Parameterized singleton (`singleton=True` + discriminator field) | Extension to ADR 009; may warrant a separate ADR |
| Prompt-as-content framing | Positions Astraeus for production AI use cases beyond CMS |
| Eval → prompt attribution pattern | Architecture documentation; core value prop for AI teams |
| Webhook-invalidated prompt cache | Reusable pattern across rules engine + prompt loader |
| Prompt diffing in admin UI | starlette-editor feature requirement for Phase 2/3 |

---

## The broader positioning implication

Prompt versioning completes the "governed data platform for AI systems" picture:

```
What data gets collected          → Item Schemas (intake forms)
How decisions get made            → Rule Configuration (governed config)
Whether decisions are correct     → Eval Dataset (human feedback)
What edge cases are tested        → Test Case Library (institutional knowledge)
How the AI behaves                → Prompt Versioning (AI governance)
```

Every artifact that affects a production AI system's behavior is now a governed document in
Astraeus. Every change has a version, a rationale, a reviewer, and a timestamp. Every deployed
version is queryable for historical audit.

This is the governed data platform claim made concrete and complete.
