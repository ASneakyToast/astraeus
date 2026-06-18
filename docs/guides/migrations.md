# Schema Versioning & Migrations

starlette-cms tracks schema versions and blocks startup when the database schema is out of sync. Migrations bring the database forward.

## How versioning works

The CMS stores the current schema version in the `cms_meta` table. On startup, it compares this to the package version. If they don't match, the CMS raises `CMSSchemaMismatch` and refuses to start:

```
CMSSchemaMismatch: Database schema version 0.3.0 does not match
package version 0.4.0. Run 'cms migrate' to apply pending migrations.
```

This ensures you never run the CMS against a database that hasn't been migrated.

## Writing a migration

Use the `@cms.migration()` decorator to register a migration function:

```python
from starlette_cms import CMS

cms = CMS(database_url="sqlite:///content.db")

@cms.migration(from_version="0.3.0", to_version="0.4.0")
async def add_priority_field(db):
    """Backfill a default priority on all task documents."""
    docs = await db.fetch_all(
        "SELECT id, body FROM cms_documents WHERE doc_type = 'task'"
    )
    for doc in docs:
        body = json.loads(doc["body"])
        if "priority" not in body:
            body["priority"] = "medium"
            await db.execute(
                "UPDATE cms_documents SET body = ? WHERE id = ?",
                json.dumps(body), doc["id"],
            )
```

The migration function receives a `db` object for running SQL. The version is updated in `cms_meta` after each step succeeds.

## Migration chains

If you have multiple versions to jump through, define a step for each:

```python
@cms.migration(from_version="0.2.0", to_version="0.3.0")
async def migrate_0_2_to_0_3(db):
    ...

@cms.migration(from_version="0.3.0", to_version="0.4.0")
async def migrate_0_3_to_0_4(db):
    ...
```

The migration runner builds an ordered chain from the current version to the target and executes each step in sequence. It raises `MigrationError` if the chain is broken (e.g. a missing step between versions).

## CLI commands

The `cms` CLI is the primary interface for running migrations. It uses `--app MODULE:ATTRIBUTE` to locate your CMS instance (or reads the `CMS_APP` environment variable):

### Check status

```bash
cms migrate status --app myapp:cms
```

Shows the stored schema version, the package version, and any pending migration steps.

### Run migrations

```bash
cms migrate run --app myapp:cms
```

Applies all pending migration steps in order. Updates the schema version after each step.

### Dry run

```bash
cms migrate run --dry-run --app myapp:cms
```

Shows what would run without actually executing anything or modifying the database.

### Validate stored documents

```bash
cms validate --app myapp:cms
```

Re-validates every stored document against the current block schemas. Exits with code 1 if any document fails validation. Useful after migrations to confirm data integrity.

## Example: adding a field with backfill

When you add a new field to an existing block, existing documents won't have it. Here's the full workflow:

**1. Add the field (with a default):**

```python
@cms.block("article")
class ArticleBlock:
    title: str = TextField(required=True)
    slug: str = TextField(required=True)
    featured: bool = BoolField(default=False)  # new field
```

**2. Write the migration:**

```python
@cms.migration(from_version="0.3.0", to_version="0.4.0")
async def backfill_featured(db):
    docs = await db.fetch_all(
        "SELECT id, body FROM cms_documents WHERE doc_type = 'article'"
    )
    for doc in docs:
        body = json.loads(doc["body"])
        body.setdefault("featured", False)
        await db.execute(
            "UPDATE cms_documents SET body = ? WHERE id = ?",
            json.dumps(body), doc["id"],
        )
```

**3. Run it:**

```bash
cms migrate run --app myapp:cms
cms validate --app myapp:cms
```

The validate step confirms all documents now pass schema validation with the new field.
