# Use Case: Structured Intake Forms (USAA VPP Underwriting)

**Status:** POC planned  
**Explored:** 2026-06-13  
**Packages:** `starlette-cms` (core), `starlette-editor` (deferred to Phase 2)  
**Roadmap impact:** Informs Phase 4 field types; validates schema API for external consumers; seeds Phase 13 (schema editor)

---

## Background

[usaa-vpp](https://github.com/ASneakyToast/usaa-vpp) is an AI-powered Valuable Personal Property underwriting demo for USAA. Users submit item intake forms (jewelry, bikes, cameras, etc.) that drive a multi-step AI workflow: document extraction, fraud detection, pricing, consistency audit, and a rules-based final decision.

The project currently encodes all SME and business logic in two disconnected places:

- **TypeScript** — form labels, field types, conditional field sets, photo slot labels
- **Pydantic** — request models with enum literals, optional fields, validation

When the underwriting team adds a new spec field (e.g. "laser inscription" for diamonds), a developer touches 4 files in 2 languages. There is no audit trail for schema changes, no versioning, and no way for a non-technical SME to inspect or propose changes.

---

## The insight

CMS concepts map naturally onto insurance intake forms:

| CMS concept          | Underwriting meaning                                          |
|----------------------|---------------------------------------------------------------|
| Block type           | Item category (JewelryItem, BikeItem, …)                     |
| Block fields         | Spec fields — carat, color grade, storage location, etc.     |
| Document             | A submitted underwriting request (one item instance)         |
| Draft → Published    | Submitted → workflow complete, decision finalized            |
| Schema version       | Which field set was active when a document was submitted      |
| Migration            | Adding/changing fields with backfill + audit trail           |
| Webhook              | Notifying downstream systems when a decision is published    |

The "content" is structured intake data rather than editorial prose — but the lifecycle, versioning, and governance needs are identical.

---

## Level 1 POC (one week of work)

### Architecture

```
usaa-vpp (FastAPI)                        Astraeus (mounted sub-app)
────────────────────────                  ─────────────────────────────────
POST /api/underwrite       ──creates──▶  starlette-cms
  ↓ runs existing workflow               ├── BlockRegistry
  ↓ publishes document on complete       │   ├── JewelryItem  (v7)
                                         │   └── BikeItem     (v3)
dev-gui React (existing)                 ├── GET /api/schema/{block_type}
├── form (schema-driven)  ◀──fetches──   ├── GET /api/documents
└── submission list       ◀──queries──   ├── Schema versioning + migrations
                                         └── Webhooks → fires on doc.published
```

`app.mount("/cms", cms.app)` — FastAPI is Starlette under the hood, no separate service needed.

### Component 1: Item schemas as CMS blocks

```python
# usaa_vpp/cms/blocks.py

from starlette_cms.fields import (
    TextField, NumberField, SelectField, BoolField, URLField, ListField
)
from starlette_cms.decorators import block

@block("jewelry_item")
class JewelryItem:
    """USAA VPP jewelry item. SME: underwriting team."""

    declared_value: NumberField(
        label="Declared Value ($)", required=True, min_value=0,
        help_text="Full replacement value as appraised"
    )
    storage_location: SelectField(
        label="Storage Location",
        choices=["bank_vault", "home_safe", "standard", "daily_wear"],
        required=True
    )
    item_description: TextField(label="Item Description", required=True)

    # Jewelry-specific specs
    carat:         NumberField(label="Carat Weight",       required=False)
    color_grade:   TextField(label="Color Grade (GIA)",    required=False)
    clarity_grade: TextField(label="Clarity Grade (GIA)",  required=False)
    metal_type:    SelectField(
        label="Metal Type",
        choices=["14K White Gold", "14K Yellow Gold", "18K White Gold", "Platinum"],
        required=False
    )

    # Supporting documents
    photo_urls:        ListField(item_type=URLField(), max_items=3, label="Photos")
    appraisal_doc_url: URLField(label="Appraisal Document", required=False)
    gia_doc_url:       URLField(label="GIA Certificate",    required=False)
```

One block per category (start with jewelry + bikes as a contrast pair). SME intent lives in
`label` and `help_text` — canonical, not duplicated across files.

### Component 2: Submissions as documents

```python
# api/router.py (modified)

@router.post("/api/underwrite")
async def underwrite(request: UnderwriteRequest):
    doc = await cms.documents.create(
        block_type="jewelry_item",
        data=request.model_dump(),
        status="draft"
    )
    job = await run_underwriting_workflow_async(
        form_data=request.model_dump(),
        document_id=doc.id
    )
    return {"job_id": job.id, "document_id": doc.id, "status": "queued"}

# In service.py, on workflow completion:
async def on_workflow_complete(job_id, result, document_id):
    await cms.documents.update(document_id, {
        "uw_status": result["uw_status"],
        "annual_premium": result["annual_premium"],
        "job_ref": job_id       # pointer to filesystem output, not the full blob
    })
    await cms.documents.publish(document_id)   # fires webhook
```

The rich AI workflow output (fraud scores, analysis JSON) stays on the filesystem. The document
stores form input, decision fields, and a `job_ref` pointer. Clean separation of concerns.

### Component 3: Schema-driven React form

```typescript
// Before — hardcoded in UnderwritePage.tsx:
const jewelryFields = [
  { key: 'carat', label: 'Carat Weight', type: 'number' },
  { key: 'color_grade', label: 'Color Grade', type: 'text' },
  // ...duplicated from somewhere
]

// After — schema-driven:
const schema = await fetch(`/cms/api/schema/jewelry_item`).then(r => r.json())
// schema.properties → every field with label, type, required, choices
// SchemaForm component renders from this automatically
```

`GET /api/schema/{block_type}` is **already implemented** in starlette-cms and returns JSON Schema
with `cms:field_meta` extensions (labels, help text, display order, choices). The POC just needs
the React side to consume it.

This is the most important POC validation: can the schema API drive an external form renderer
without starlette-editor? If yes, the editor architecture is de-risked before Phase 10.

### Component 4: A live migration (the demo highlight)

Scenario — Q3 planning, SME says "track laser inscription on diamonds for fraud detection now."

**Today:** developer edits 4 files in 2 languages, no audit trail.

**With POC:**

```python
# 1. Edit the block (one place):
@block("jewelry_item")
class JewelryItem:
    # ... existing fields unchanged ...
    laser_inscription: BoolField(
        label="Has Laser Inscription", default=False,
        help_text="GIA laser inscription on diamonds >0.18ct, added 2023+"
    )
    laser_inscription_code: TextField(label="Inscription Code", required=False)

# 2. Write the migration (scaffolded, you fill the logic):
@migration(from_version=6, to_version=7, block_type="jewelry_item")
def add_laser_inscription(document: dict) -> dict:
    document["laser_inscription"] = False
    document["laser_inscription_code"] = None
    return document
```

Run `uv run astraeus migrate`. What USAA sees:
- All 500 existing submissions show `laser_inscription: false` (backfilled)
- New submissions have the field in the form (schema-driven UI auto-updates)
- Migration log records timestamp, deployer, version delta
- Old submissions still queryable at v6 for audit

### Component 5: Webhook (infrastructure for Level 2)

```json
POST https://usaa-portal.example.com/webhooks/underwriting
{
  "event": "document.published",
  "block_type": "jewelry_item",
  "schema_version": 7,
  "document_id": "doc_01j...",
  "data": {
    "uw_status": "auto_approved",
    "annual_premium": 80.00,
    "declared_value": 8000.00
  }
}
```

In Level 1 this is infrastructure. In Level 2, schema-change events use the same mechanism to
notify downstream systems to reload validation logic — the hook is there from day one.

---

## What the POC demo looks like (20 minutes)

1. **"Here's the jewelry schema"** — `/cms/api/schema/jewelry_item` in the browser. Every field
   with label, type, required flag, choices. "This is the single source of truth. The form and
   the API validation both come from here."

2. **"Here's every submission"** — document list view. Click one, see full form data + decision +
   timestamp + schema version it was submitted on.

3. **"Watch a field get added"** — live: add `laser_inscription`, run migration, refresh schema
   endpoint. The form now has the new field. The 500 old submissions still work. Migration log
   records what happened and when.

4. **"The audit trail"** — "On April 15 at 2:34pm, schema v7 was deployed. Submissions before
   this point are on v6. All after are on v7. We can query either set."

5. **"Here's Level 2"** — sketch the schema editor: "Instead of a developer changing Python code,
   your underwriting SME changes this via a UI and clicks Publish. The migration runs
   automatically." This is starlette-editor Phase 2 work; the API contract is already in place.

---

## Build breakdown

**In `starlette-cms` (pure Astraeus work, reusable):**
- `NumberField(min_value, max_value)` — Phase 4 field type
- `SelectField(choices)` — Phase 4 field type
- `BoolField(default)` — Phase 4 field type
- `URLField` — Phase 4 field type

**In `usaa-vpp` (~200 lines):**
- `usaa_vpp/cms/blocks.py` — 2 block definitions (JewelryItem, BikeItem)
- `usaa_vpp/cms/app.py` — CMS instance, mounted into FastAPI
- Modified `POST /api/underwrite` — creates draft, publishes on completion
- 1 demonstration migration

**In `dev-gui` React (~100 lines changed):**
- `useBlockSchema(blockType)` hook
- `SchemaForm` component (renders fields from `cms:field_meta`)
- Replaces hardcoded field arrays in `UnderwritePage.tsx`

**In `starlette-editor` — nothing. Explicitly deferred.** The POC validates the API design
first; if it works, editor Phase 1 is worth building.

---

## Learning goals

| Question | How the POC answers it |
|---|---|
| Does starlette-cms model typed intake forms, not just editorial content? | Writing 2 blocks reveals this immediately |
| Is draft→published the right lifecycle, or do we need more states? | Real workflow integration will expose gaps |
| Can the schema API drive an external React form? | SchemaForm component directly answers this |
| What field types are missing from starlette-cms? | Writing the blocks surfaces every gap |
| What does the migration DX feel like in practice? | One real migration — is the API good enough? |
| Is Level 2 (SME-editable schemas) worth building? | If USAA says "can we change fields without deploying?" — yes |

---

## Roadmap implications

| POC output | Astraeus impact |
|---|---|
| NumberField, SelectField, BoolField, URLField | **Phase 4** — new field types |
| Schema API validated against external React consumer | **Phase 10** (editor Phase 1) de-risked |
| Real migration written under real constraints | Migration runner battle-tested |
| Intake forms as second major use case | Broadens starlette-cms positioning in docs |
| USAA feedback on Level 2 | Feature brief for **Phase 13** — schema editor |

---

## Level 2 (future — not in scope for POC)

Schema definitions stored in the database, not Python code. SME adds a field via the editor UI,
publishes it, workflow engine reloads. No developer involved.

The distance between the current architecture and Level 2 is smaller than it looks:

```
Today:    BlockRegistry (Python)     → /api/editor-schema → browser
Level 2:  SchemaStore (Database)     → /api/editor-schema → browser
```

The browser side is unchanged — it consumes the same endpoint. The gap is:
1. A database representation for block type definitions
2. An admin UI to add/edit/publish field definitions (schema editor mode in starlette-editor)
3. The schema endpoint reads from the DB instead of the registry

This is Phase 13 / editor Phase 4. The POC generates the real user feedback needed to design it.
