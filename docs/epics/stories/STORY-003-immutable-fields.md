# STORY-003 — Immutable fields (`immutable=True`)

**Epic:** [EPIC-001](../EPIC-001-vpp-mvp.md)  
**Status:** Ready  
**Depends on:** STORY-001 (for `_BaseField` extension pattern)  
**Blocks:** Nothing (independent, can run in parallel with STORY-002)

---

## Goal

Add `immutable=True` to `_BaseField` per ADR 013 pt.1. Fields marked immutable are silently
stripped from PATCH bodies before the merge step. They are written normally on create.

This is a self-contained change with no dependency on ADR 012 (identity/permission).

---

## Changes required

### `fields.py`

Add `immutable: bool = False` to `_BaseField` and surface it in `field_meta()`:

```python
@dataclass
class _BaseField:
    required: bool = False
    label: str | None = None
    placeholder: str | None = None
    help_text: str | None = None
    display_order: int | None = None
    group: str | None = None
    immutable: bool = False        # ← new

    def field_meta(self) -> dict[str, Any]:
        meta = {
            k: v
            for k, v in {
                "label": self.label,
                "placeholder": self.placeholder,
                "help_text": self.help_text,
                "display_order": self.display_order,
                "group": self.group,
            }.items()
            if v is not None
        }
        if self.immutable:
            meta["immutable"] = True   # only include when True — keeps schema clean
        return meta
```

All field subclasses inherit this automatically.

### `model_builder.py`

Add a helper to extract immutable field names from a block's original class definition:

```python
def get_immutable_fields(cls: type) -> set[str]:
    """Return the set of field names that are marked immutable=True."""
    result = set()
    for attr_name, value in vars(cls).items():
        if isinstance(value, _BaseField) and value.immutable:
            result.add(attr_name)
    return result
```

Store on the generated model class:

```python
def build_block_model(name: str, cls: type) -> type[pydantic.BaseModel]:
    ...
    model.__immutable_fields__ = get_immutable_fields(cls)   # ← new
    ...
    return model
```

Same pattern as `__image_fields__` already on document models.

### `api/documents.py` — `patch_document`

Add the immutable-field strip step before the merge:

```python
async def patch_document(request: Request) -> JSONResponse:
    ...
    new_body_data = patch_data.get("body", {})

    # Strip immutable fields — silently, no error
    if doc_model is not None:
        immutable = getattr(doc_model, "__immutable_fields__", set())
        for field_name in immutable:
            new_body_data.pop(field_name, None)

    merged_body = {**existing_body, **new_body_data}
    ...
```

This is inserted **before** the `Validation merged body` block, and before any future
permission-allowlist strip (ADR 013 pt.2).

---

## Usage example

```python
@cms.block("eval_entry")
class EvalEntry:
    submission_ref: DocumentRef(block_type="jewelry_item", immutable=True)
    rule_config_ref: DocumentRef(block_type="global_thresholds", immutable=True)
    uw_status: SelectField(choices=["auto_approved","manual_review"], immutable=True)

    score: SelectField(choices=["1","2","3","4","5"], required=True)
    notes: TextField(label="Notes", required=False)
```

A PATCH with `{ "body": { "submission_ref": "doc_new_id", "score": "5" } }` results in:
- `submission_ref` silently dropped
- `score` applied normally

---

## Schema API

`GET /api/schema/eval_entry` returns:

```json
{
  "properties": {
    "submission_ref": {
      "cms:field_meta": {
        "label": "Submission",
        "immutable": true
      }
    },
    "score": {
      "cms:field_meta": {
        "label": "Score",
        "choices": ["1","2","3","4","5"]
      }
    }
  }
}
```

The `"immutable": true` flag is only included when `immutable=True` — not present at all
for mutable fields. This allows form renderers to conditionally render fields as read-only.

---

## Tests

### `tests/test_documents.py` additions

- `test_immutable_field_ignored_on_patch` — PATCH with immutable field returns 200 but field unchanged
- `test_immutable_field_written_on_create` — immutable field is written normally at create time
- `test_mutable_fields_still_patchable` — non-immutable fields on same doc patch correctly
- `test_immutable_on_non_block_field` — `TextField(immutable=True)` also strips correctly

### `tests/test_schema.py` additions

- `test_immutable_field_in_schema` — `cms:field_meta.immutable: true` present for immutable field
- `test_mutable_field_no_immutable_key` — `"immutable"` key absent for mutable fields (cleanliness)

### `tests/test_block_decorator.py` additions

- `test_immutable_fields_collected` — `model.__immutable_fields__` contains correct names
- `test_non_immutable_not_in_set` — mutable fields not in `__immutable_fields__`

---

## Definition of done

- [ ] `immutable: bool = False` on `_BaseField`
- [ ] `field_meta()` includes `"immutable": True` only when flag is set
- [ ] `build_block_model()` populates `__immutable_fields__` on the model
- [ ] `patch_document` strips immutable fields before merge
- [ ] Immutable fields ARE written on create (not stripped there)
- [ ] All tests above pass
- [ ] `GET /api/schema` surfaces `immutable: true` in `cms:field_meta`
- [ ] No regressions
