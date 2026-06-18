# STORY-004 — Document references (`DocumentRef`)

**Epic:** [EPIC-001](../EPIC-001-vpp-mvp.md)  
**Status:** Ready  
**Depends on:** STORY-001 (field type architecture), STORY-003 (`immutable=True` for ref fields)  
**Blocks:** STORY-005 (list filters use DocumentRef in test scenarios)

---

## Goal

Implement `DocumentRef(block_type)` as a first-class field type per ADR 010. A `DocumentRef`
stores a document ID string, validates at write time that the target exists with the declared
block type, and supports lazy async resolution.

---

## Changes required

### `fields.py`

```python
@dataclass
class DocumentRef(_BaseField):
    """
    A typed foreign key to another document.

    Stores the target document's ID string. Validates on write that the
    referenced document exists and has the declared block_type.

    ``on_delete`` controls behaviour when the referenced document is deleted:
    - ``"block"``   — refuse to delete the target (default)
    - ``"nullify"`` — set this field to None in all referencing documents
    - ``"cascade"`` — delete all documents referencing the target (dangerous)

    Example::

        submission_ref: DocumentRef(block_type="jewelry_item", immutable=True)
    """
    block_type: str | None = None
    on_delete: str = "block"   # "block" | "nullify" | "cascade"

    def field_meta(self) -> dict[str, Any]:
        meta = super().field_meta()
        if self.block_type:
            meta["ref_block_type"] = self.block_type
        meta["on_delete"] = self.on_delete
        meta["field_type"] = "document_ref"
        return meta
```

### `model_builder.py`

Add `DocumentRef` to imports and handle in `_make_field()`:

```python
if isinstance(default, DocumentRef):
    # Stored as str (the document ID); resolution is runtime, not Pydantic
    if optional:
        return (str | None, Field(default=None, json_schema_extra=extra))
    return (str, Field(..., json_schema_extra=extra))
```

Also collect `DocumentRef` fields on the model for runtime use:

```python
def build_block_model(name: str, cls: type) -> type[pydantic.BaseModel]:
    ...
    model.__ref_fields__ = {
        attr: value
        for attr, value in vars(cls).items()
        if isinstance(value, DocumentRef)
    }  # dict[str, DocumentRef] — maps field name to its DocumentRef descriptor
    ...
```

### `api/documents.py` — write-time validation

In `create_document` and `patch_document`, after Pydantic validation and before persisting:

```python
async def _validate_refs(cms, doc_model, body_data: dict) -> JSONResponse | None:
    """
    For each DocumentRef field in body_data, verify the referenced document exists
    and has the correct block_type. Returns a 422 JSONResponse on failure, None on success.
    """
    ref_fields: dict = getattr(doc_model, "__ref_fields__", {})
    for field_name, ref_descriptor in ref_fields.items():
        ref_id = body_data.get(field_name)
        if ref_id is None:
            continue   # optional ref not provided — skip
        if not isinstance(ref_id, str):
            return JSONResponse(
                {"error": f"{field_name}: DocumentRef must be a string ID"},
                status_code=422,
            )
        # Check existence and type
        rows = await CMSDocument.select(CMSDocument.doc_type).where(
            CMSDocument.id == ref_id
        ).limit(1).run()
        if not rows:
            return JSONResponse(
                {"error": f"{field_name}: referenced document {ref_id!r} not found"},
                status_code=422,
            )
        if ref_descriptor.block_type and rows[0]["doc_type"] != ref_descriptor.block_type:
            return JSONResponse(
                {
                    "error": (
                        f"{field_name}: expected block_type {ref_descriptor.block_type!r}, "
                        f"got {rows[0]['doc_type']!r}"
                    )
                },
                status_code=422,
            )
    return None
```

Call this in `create_document` after Pydantic validation:

```python
if (err := await _validate_refs(cms, doc_model, validated.model_dump())) is not None:
    return err
```

And in `patch_document` after immutable-field stripping, before final merge:

```python
if (err := await _validate_refs(cms, doc_model, new_body_data)) is not None:
    return err
```

### `api/documents.py` — `delete_document` ref integrity

Before deleting a document, check if anything references it with `on_delete="block"`:

```python
async def _check_ref_integrity(doc_id: str, doc_type: str) -> JSONResponse | None:
    """
    Scan all registered block types for DocumentRef fields pointing at this doc_type
    with on_delete="block". If any referencing documents exist, return 409.
    """
    # This requires cms reference — pass cms into function
    for block_name, registration in cms.registry._blocks.items():
        ref_fields = getattr(registration.model, "__ref_fields__", {})
        for field_name, ref_desc in ref_fields.items():
            if ref_desc.block_type != doc_type:
                continue
            if ref_desc.on_delete != "block":
                continue
            # Check if any document of block_name has this doc_id in field_name
            # This requires JSON contains query — use raw SQL or Piccolo where appropriate
            count = await CMSDocument.count().where(
                CMSDocument.doc_type == block_name,
                # Piccolo JSON contains: approximate via LIKE for SQLite v1
                # Use raw for correctness:
            ).run()
            # v1 simplification: scan in Python (acceptable for < 10k docs)
            rows = await CMSDocument.select(CMSDocument.id, CMSDocument.body).where(
                CMSDocument.doc_type == block_name
            ).run()
            for row in rows:
                body = json.loads(row["body"]) if isinstance(row["body"], str) else row["body"]
                if body.get(field_name) == doc_id:
                    return JSONResponse(
                        {"error": f"Cannot delete: referenced by {block_name}.{field_name}"},
                        status_code=409,
                    )
    return None
```

> **v1 note:** The Python-scan approach is acceptable for the VPP POC scale (< 1k documents).
> Add a DB-level JSON index query in a follow-on story for production scale.

### `api/documents.py` — `resolve_refs` on list

Add optional `resolve_refs` query parameter to `GET /api/documents`:

```
GET /api/documents?type=eval_entry&resolve_refs=submission_ref,rule_config_ref
```

When `resolve_refs` is provided, after fetching the document list, bulk-resolve each named
ref field with a single `IN (...)` query per field:

```python
async def _bulk_resolve_refs(docs: list[dict], resolve_fields: list[str]) -> list[dict]:
    for field_name in resolve_fields:
        ids = [d["body"].get(field_name) for d in docs if d["body"].get(field_name)]
        if not ids:
            continue
        ref_rows = await CMSDocument.select().where(
            CMSDocument.id.is_in(ids)
        ).run()
        ref_map = {r["id"]: _row_to_dict(r) for r in ref_rows}
        for doc in docs:
            ref_id = doc["body"].get(field_name)
            if ref_id and ref_id in ref_map:
                doc["body"][f"{field_name}__resolved"] = ref_map[ref_id]
    return docs
```

Resolved data is placed at `field_name__resolved` alongside the raw ID. Callers can use
either. This avoids mutating the stored body format.

### `exceptions.py`

```python
class DocumentNotFound(CMSError): ...      # if not already from STORY-002
class BlockTypeMismatch(CMSError): ...     # ref points at wrong block_type
class ReferencedDocumentError(CMSError):  # on_delete="block" violation
    ...
```

---

## Tests

### `tests/test_documents.py` additions

- `test_create_document_with_valid_ref` — creates doc with DocumentRef pointing at existing doc
- `test_create_document_invalid_ref_id` — 422 when ref ID does not exist
- `test_create_document_wrong_block_type_ref` — 422 when ref points at wrong block_type
- `test_patch_document_validates_new_ref` — PATCH with new ref validates it
- `test_delete_blocked_by_ref` — 409 when on_delete="block" and referencing doc exists
- `test_delete_nullifies_ref` — on_delete="nullify" sets ref to None in referencing doc
- `test_resolve_refs_in_list` — `?resolve_refs=submission_ref` returns `__resolved` keys
- `test_resolve_refs_no_n_plus_one` — single IN query per ref field (mock DB to verify)

### `tests/test_block_decorator.py` additions

- `test_documentref_field_type_is_str` — generated Pydantic field is `str | None`
- `test_documentref_field_meta_includes_ref_block_type`
- `test_documentref_ref_fields_dict_on_model` — `model.__ref_fields__` populated correctly
- `test_documentref_optional_defaults_none`

### `tests/test_schema.py` additions

- `test_documentref_schema_includes_ref_block_type` — `cms:field_meta.ref_block_type` present
- `test_documentref_schema_field_type_marker` — `cms:field_meta.field_type == "document_ref"`

---

## Definition of done

- [ ] `DocumentRef` defined in `fields.py` with `block_type`, `on_delete`, `immutable` support
- [ ] `DocumentRef` wired through `_make_field()` as `str | None`
- [ ] `__ref_fields__` dict populated on block models by `build_block_model()`
- [ ] Write-time validation in `create_document` and `patch_document`
- [ ] `delete_document` enforces `on_delete="block"` (409 on violation)
- [ ] `delete_document` applies `on_delete="nullify"` (sets ref to None in referencing docs)
- [ ] `GET /api/documents?resolve_refs=field` bulk-resolves refs with O(1) queries per field
- [ ] `DocumentRef` exported from `starlette_cms/__init__.py`
- [ ] All tests above pass
- [ ] No regressions
