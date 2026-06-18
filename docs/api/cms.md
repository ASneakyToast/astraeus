# API Reference: CMS Class

```python
from starlette_cms import CMS
```

## Constructor

```python
CMS(
    *,
    database_url: str,
    auth: str | Callable = "none",
    api_key: str | None = None,
    read_auth: bool = False,
    mount_path: str = "/cms",
    discover_blocks: bool = False,
    media_backend: MediaBackend | None = None,
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `database_url` | `str` | required | SQLite or Postgres connection string |
| `auth` | `str \| Callable` | `"none"` | `"none"`, `"apikey"`, or an async callable `(request) -> bool` |
| `api_key` | `str \| None` | `None` | Required when `auth="apikey"` |
| `read_auth` | `bool` | `False` | If `True`, GET endpoints also require auth |
| `mount_path` | `str` | `"/cms"` | Base path used for self-referential links |
| `discover_blocks` | `bool` | `False` | Auto-discover blocks via entry points |
| `media_backend` | `MediaBackend \| None` | `None` | Backend for `ImageField` validation |

## Block registration

### `@cms.block(name, *, singleton=False, override=False)`

Decorator that defines a block type, converts the class to a Pydantic model, and registers it with the CMS. Returns the generated Pydantic model class.

```python
@cms.block("hero")
class HeroBlock:
    title: str = TextField(required=True)
    subtitle: str = TextField()
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | required | Unique block type name |
| `singleton` | `bool` | `False` | Mark as a singleton type |
| `override` | `bool` | `False` | Allow re-registration of an existing name |

### `cms.register_block(block_cls, *, override=False)`

Register a pre-decorated block class programmatically. The class must already have `__block_type__` set (via the standalone `@block()` decorator).

```python
from starlette_cms import block

@block("gallery")
class GalleryBlock:
    heading: str = TextField(required=True)

cms.register_block(GalleryBlock)
```

### `cms.register_blocks(block_classes, *, override=False)`

Register multiple block classes at once.

```python
cms.register_blocks([GalleryBlock, CardBlock, QuoteBlock])
```

## Document registration

### `@cms.document(name)`

Decorator that converts a class to a document-level Pydantic model and registers it. Similar to `@cms.block()` but for document container types.

```python
@cms.document("page")
class PageDocument:
    title: str = TextField(required=True)
    slug: str = TextField(required=True)
    sections: list = ListField(blocks=[HeroBlock, TextBlock])
```

## Extension routes

### `cms.register_extension_route(*, path, endpoint, methods, name)`

Register an additional route on the CMS app. Must be called **before** first access to `cms.app`.

```python
cms.register_extension_route(
    path="/api/custom",
    endpoint=my_handler,
    methods=["GET"],
    name="custom_endpoint",
)
```

Raises `RuntimeError` if called after `cms.app` has been accessed.

## Migration

### `@cms.migration(*, from_version, to_version)`

Register a migration function for upgrading between schema versions.

```python
@cms.migration(from_version="0.3.0", to_version="0.4.0")
async def my_migration(db):
    ...
```

See [Schema Versioning & Migrations](../guides/migrations.md) for details.

## Properties

### `cms.app -> Starlette`

The CMS sub-application. **Lazy** — built on first access. All block registrations and extension routes must happen before this is accessed.

```python
from starlette.routing import Mount

app = Starlette(routes=[Mount("/cms", app=cms.app)])
```

### `cms.documents -> CMSDocuments`

Python accessor for document operations. See [CMSDocuments](#cmsdocuments) below.

### `cms.registry -> BlockRegistry`

The block registry instance. Supports:

- `cms.registry.get(name)` — get a block model by name, raises `BlockNotFound`
- `cms.registry.all()` — dict of all registered block models
- `cms.registry.names()` — list of all block type names
- `cms.registry.is_singleton(name)` — check if a block type is a singleton
- `"name" in cms.registry` — containment check

## Lifespan

### `cms.lifespan(app)`

Standalone lifespan context manager — use when the CMS is the only package managing the app lifecycle.

```python
app = Starlette(routes=[...], lifespan=cms.lifespan)
```

### `cms.lifespan_context(app)`

Composable lifespan context manager — use when composing with other packages.

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    async with cms.lifespan_context(app):
        async with media.lifespan_context(app):
            yield

app = Starlette(routes=[...], lifespan=lifespan)
```

---

## CMSDocuments

Available via `cms.documents`.

### `await cms.documents.get_singleton(block_type) -> dict`

Returns the currently active singleton document. Raises `DocumentNotFound` if none has been published.

```python
config = await cms.documents.get_singleton("site_config")
print(config["body"]["site_name"])
```

### `await cms.documents.list(block_type, *, filters=None, published=None, limit=100, offset=0) -> list[dict]`

List documents of a given block type.

```python
articles = await cms.documents.list(
    "article",
    filters={"status": "published"},
    published=True,
    limit=50,
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `block_type` | `str` | required | Block type name to filter by |
| `filters` | `dict \| None` | `None` | Body field filters |
| `published` | `bool \| None` | `None` | Filter by publish state |
| `limit` | `int` | `100` | Max results |
| `offset` | `int` | `0` | Pagination offset |
