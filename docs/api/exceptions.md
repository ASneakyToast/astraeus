# API Reference: Exceptions

All public exceptions are importable from `starlette_cms`:

```python
from starlette_cms import (
    CMSSchemaMismatch,
    BlockNotFound,
    BlockRegistrationError,
    BlockTypeMismatch,
    ReferencedDocumentError,
    DocumentNotFound,
    SingletonConflict,
)
```

---

## CMSSchemaMismatch

Raised on startup when the database schema version doesn't match the package version.

```python
try:
    async with cms.lifespan_context(app):
        ...
except CMSSchemaMismatch as e:
    print(f"Run 'cms migrate' first: {e}")
```

**When it's raised:** During CMS lifespan startup, when the stored `schema_version` in `cms_meta` differs from the package version.

**How to fix:** Run `cms migrate run --app myapp:cms` to apply pending migrations.

---

## BlockNotFound

Raised when a block type name is not found in the registry.

```python
try:
    model = cms.registry.get("nonexistent")
except BlockNotFound:
    print("Block type not registered")
```

**When it's raised:** `cms.registry.get(name)` when `name` is not registered.

---

## BlockRegistrationError

Raised when a block type name collision occurs during registration.

```python
try:
    cms.register_block(DuplicateBlock)
except BlockRegistrationError:
    print("Block type name already taken")
```

**When it's raised:** `cms.register_block()` or `@cms.block()` when the name is already registered and `override=False`.

---

## BlockTypeMismatch

Raised when a `DocumentRef` target has an unexpected `block_type`.

**When it's raised:** On `POST /api/documents` or `PATCH /api/documents/{id}` when a `DocumentRef` field points to a document whose `doc_type` doesn't match the declared `block_type`.

**HTTP response:** `422 Unprocessable Entity`.

---

## ReferencedDocumentError

Raised when a delete is blocked by referential integrity (`on_delete="block"`).

**When it's raised:** On `DELETE /api/documents/{id}` when other documents reference this one via `DocumentRef(on_delete="block")`.

**HTTP response:** `409 Conflict` with the count of referencing documents.

---

## DocumentNotFound

Raised when a document ID is not found in the database.

```python
from starlette_cms.exceptions import DocumentNotFound

try:
    config = await cms.documents.get_singleton("site_config")
except DocumentNotFound:
    print("No active singleton found")
```

**When it's raised:** `cms.documents.get_singleton()` when no active singleton exists for the given block type.

---

## SingletonConflict

Raised when a singleton publish violates the one-active constraint.

```python
from starlette_cms.exceptions import SingletonConflict
```

**When it's raised:** Internal constraint violation during singleton operations. Typically handled by the API layer rather than user code.

---

## MigrationError

Available from the migrations module:

```python
from starlette_cms.migrations import MigrationError
```

**When it's raised:** When the migration chain is broken, has duplicate steps, or contains cycles.
