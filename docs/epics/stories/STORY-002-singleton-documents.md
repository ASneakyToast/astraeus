# STORY-002 — Singleton documents

**Epic:** [EPIC-001](../EPIC-001-vpp-mvp.md)  
**Status:** Ready  
**Depends on:** STORY-001 (for `NumberField` used in examples; registry changes must land first)  
**Blocks:** Nothing in Tier 1/2 (Tier 3 prompt versioning needs parameterized variant)

---

## Goal

Implement `singleton=True` as a first-class block modifier per ADR 009. A singleton block
has exactly one published document at any time. Publishing a new version atomically archives
the previous one. `cms.documents.get_singleton(block_type)` returns the live published
document directly.

---

## Changes required

### `fields.py` — no changes

### `registry.py`

`BlockRegistry.register_block()` must accept and store `singleton: bool`:

```python
class BlockRegistration:
    """Metadata stored alongside each registered block model."""
    model: type
    singleton: bool = False

class BlockRegistry:
    _blocks: dict[str, BlockRegistration]   # was dict[str, type]

    def register_block(self, block_cls, *, override=False, singleton=False) -> None:
        ...
        self._blocks[name] = BlockRegistration(model=model_cls, singleton=singleton)

    def get(self, name: str) -> type:
        return self._blocks[name].model

    def is_singleton(self, name: str) -> bool:
        if name not in self._blocks:
            raise BlockNotFound(...)
        return self._blocks[name].singleton
```

The `@cms.block("name", singleton=True)` decorator must pass `singleton=True` to
`register_block`. Update the decorator in `app.py`.

### `app.py`

```python
def block(self, name: str, *, singleton: bool = False, override: bool = False):
    def decorator(cls):
        cls.__block_type__ = name
        cls.__singleton__ = singleton
        self.registry.register_block(cls, override=override, singleton=singleton)
        return cls
    return decorator
```

### `tables.py`

Add `status` column to `CMSDocument` to distinguish `active` vs `archived`:

```python
class CMSDocument(Table):
    ...
    # existing columns unchanged
    singleton_status = Varchar(length=16, default="")
    # values: "" (regular doc), "active" (current singleton publish), "archived" (superseded)
```

> **Note:** Using `singleton_status` (not `status`) to avoid collision with future
> draft/published distinction work. Empty string = regular document, unchanged semantics.

This requires a migration. Add to `starlette_cms/migrations/` a new migration file that
`ALTER TABLE cms_documents ADD COLUMN singleton_status VARCHAR(16) DEFAULT ''`.

### `api/documents.py`

#### `publish_document` — singleton enforcement

When publishing a singleton document, wrap in a transaction:
1. Find any existing `singleton_status='active'` row for the same `doc_type`
2. Set it to `singleton_status='archived'`
3. Set the new document to `singleton_status='active'` and `published=True`

```python
# Pseudo-code for the singleton publish path:
reg = cms.registry
if reg.is_singleton(doc_type):
    async with transaction():
        # Archive the currently active singleton (if any)
        await CMSDocument.update({
            CMSDocument.singleton_status: "archived"
        }).where(
            CMSDocument.doc_type == doc_type,
            CMSDocument.singleton_status == "active"
        ).run()
        # Activate the new one
        await CMSDocument.update({
            CMSDocument.published: True,
            CMSDocument.published_at: now,
            CMSDocument.singleton_status: "active",
            CMSDocument.updated_at: now,
        }).where(CMSDocument.id == doc_id).run()
else:
    # existing non-singleton publish path
    ...
```

Add `"singleton": True` to the webhook payload when `is_singleton(doc_type)` is True.

#### `get_singleton` — new convenience function

Add a new route and helper accessible via `cms.documents`:

```
GET /api/documents/singleton/{block_type}
```

Returns the current `singleton_status='active'` document for the block type, or 404 if
none published. Does not require changing the existing list/get routes.

Also expose programmatically on a `CMSDocuments` accessor:

```python
# In app.py:
class CMSDocuments:
    def __init__(self, cms): self._cms = cms

    async def get_singleton(self, block_type: str) -> dict:
        rows = await CMSDocument.select().where(
            CMSDocument.doc_type == block_type,
            CMSDocument.singleton_status == "active",
        ).limit(1).run()
        if not rows:
            raise DocumentNotFound(f"No published singleton for {block_type!r}")
        return _row_to_dict(rows[0])

# Attached to CMS:
@property
def documents(self) -> CMSDocuments:
    return CMSDocuments(self)
```

#### `publish_singleton` — write path

Add `POST /api/documents/singleton/{block_type}` that creates-and-publishes in one step
(for seed scripts):

```
POST /api/documents/singleton/{block_type}
Body: { "body": {...}, "version_message": "..." }
```

Stores `version_message` in the document `meta` field.

#### `get_singleton_history`

```
GET /api/documents/singleton/{block_type}/history
```

Returns all `singleton_status='archived'` rows for the type, ordered newest first.

### `exceptions.py`

Add:
```python
class DocumentNotFound(CMSError): ...   # if not already present
class SingletonConflict(CMSError): ...  # attempt to publish when active != expected
```

---

## Migration

File: `starlette_cms/migrations/002_singleton_status.py`

```python
"""Add singleton_status column to cms_documents."""

from piccolo.apps.migrations.auto.migration_manager import MigrationManager

ID = "2026-06-13T00:00:00"
VERSION = "0.1.0"
DESCRIPTION = "Add singleton_status column"

async def forwards():
    manager = MigrationManager(migration_id=ID, app_name="starlette_cms", description=DESCRIPTION)
    manager.alter_column(
        table_class_name="CMSDocument",
        tablename="cms_documents",
        column_name="singleton_status",
        db_column_name="singleton_status",
        params={"default": "", "length": 16},
        old_params=None,
        column_class_value=0,
        old_column_class_value=None,
    )
    return manager
```

The startup schema version check must run this migration automatically (or `cms migrate`
applies it).

---

## Tests

### `tests/test_documents.py` additions

- `test_singleton_publish_archives_previous` — publish v2, verify v1 is archived
- `test_singleton_publish_requires_one_active` — can't have two active singletons
- `test_get_singleton_returns_active` — GET /api/documents/singleton/storage_rates works
- `test_get_singleton_404_when_none_published` — 404 before first publish
- `test_singleton_history_ordered` — /history returns archived docs newest-first
- `test_publish_singleton_endpoint` — POST /api/documents/singleton/{type} creates + publishes
- `test_non_singleton_publish_unaffected` — regular document publish behaviour unchanged
- `test_singleton_webhook_payload_includes_flag` — webhook payload has `"singleton": true`

### `tests/test_registry.py` additions

- `test_singleton_flag_stored` — `registry.is_singleton("storage_rates")` is True
- `test_non_singleton_flag_false` — `registry.is_singleton("jewelry_item")` is False
- `test_singleton_get_returns_model` — `registry.get("storage_rates")` still works

---

## Definition of done

- [ ] `singleton=True` accepted by `@cms.block()` and `@block()` decorators
- [ ] `BlockRegistration` dataclass in registry stores `singleton`
- [ ] `singleton_status` column added to `CMSDocument` via migration
- [ ] `publish_document` enforces singleton semantics (archive-then-activate)
- [ ] `GET /api/documents/singleton/{block_type}` returns active singleton or 404
- [ ] `POST /api/documents/singleton/{block_type}` creates + publishes in one step
- [ ] `GET /api/documents/singleton/{block_type}/history` returns archived versions
- [ ] `cms.documents.get_singleton()` Python accessor works
- [ ] Webhook payload includes `"singleton": true` for singleton publishes
- [ ] All tests above pass
- [ ] Migration file present and applied by `cms migrate`
- [ ] No regressions
