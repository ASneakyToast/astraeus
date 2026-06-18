# Getting Started

This guide gets you from zero to a running CMS in under 5 minutes.

## Install

```bash
pip install starlette-cms
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add starlette-cms
```

## Define your blocks

A **block** is a content type. Define it as a Python class with field annotations:

```python
# app.py
from starlette_cms import CMS, TextField, RichTextField, ImageField, ListField

cms = CMS(database_url="sqlite:///content.db")

@cms.block("hero")
class HeroBlock:
    title: str = TextField(required=True, label="Headline")
    subtitle: str = TextField()
    image: str = ImageField(label="Background image")

@cms.block("text")
class TextBlock:
    body: dict = RichTextField(required=True)
```

The `@cms.block()` decorator converts your class into a Pydantic model with full validation, and registers it with the CMS.

## Define a document type

A **document** is a container for blocks. Define one with `@cms.document()`:

```python
@cms.document("page")
class PageDocument:
    title: str = TextField(required=True)
    slug: str = TextField(required=True)
    sections: list = ListField(blocks=[HeroBlock, TextBlock])
```

`ListField(blocks=[...])` creates a polymorphic list — each item is validated against the correct block type using a `block_type` discriminator.

## Mount into your app

```python
from starlette.applications import Starlette
from starlette.routing import Mount

app = Starlette(
    routes=[Mount("/cms", app=cms.app)],
    lifespan=cms.lifespan,
)
```

Start it:

```bash
uvicorn app:app --reload
```

## Create a document

```bash
curl -X POST http://localhost:8000/cms/api/documents \
  -H "Content-Type: application/json" \
  -d '{
    "doc_type": "page",
    "slug": "home",
    "body": {
      "title": "Welcome",
      "slug": "home",
      "sections": [
        {
          "block_type": "hero",
          "title": "Hello, world",
          "subtitle": "Built with Astraeus"
        },
        {
          "block_type": "text",
          "body": {
            "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "This is rich text."}]}]
          }
        }
      ]
    }
  }'
```

The response includes the document's `id` (a nanoid), timestamps, and the validated body.

## Query it back

```bash
# List all page documents
curl http://localhost:8000/cms/api/documents?type=page

# Get by ID
curl http://localhost:8000/cms/api/documents/{id}

# Filter by slug
curl http://localhost:8000/cms/api/documents?type=page&filter[slug]=home
```

## Publish it

```bash
curl -X POST http://localhost:8000/cms/api/documents/{id}/publish
```

Publishing sets `published=true` and `published_at` to the current time. Any registered [webhooks](guides/webhooks.md) fire on publish.

## Add authentication

By default, all endpoints are open. For production, add API key auth:

```python
cms = CMS(
    database_url="sqlite:///content.db",
    auth="apikey",
    api_key="your-secret-key",
)
```

Mutating endpoints (POST, PATCH, DELETE) now require `Authorization: Bearer your-secret-key`. Add `read_auth=True` to protect GET endpoints too.

## Introspect the schema

```bash
# All block schemas
curl http://localhost:8000/cms/api/schema

# One block type
curl http://localhost:8000/cms/api/schema/hero
```

The schema response includes JSON Schema plus `field_meta` with labels, help text, display order, and other editor hints.

## Full working example

```python
from starlette_cms import CMS, TextField, RichTextField, ImageField, ListField
from starlette.applications import Starlette
from starlette.routing import Mount

cms = CMS(database_url="sqlite:///content.db", auth="apikey", api_key="secret")

@cms.block("hero")
class HeroBlock:
    title: str = TextField(required=True, label="Headline")
    subtitle: str = TextField()
    image: str = ImageField(label="Background image")

@cms.block("text")
class TextBlock:
    body: dict = RichTextField(required=True)

@cms.document("page")
class PageDocument:
    title: str = TextField(required=True)
    slug: str = TextField(required=True)
    sections: list = ListField(blocks=[HeroBlock, TextBlock])

app = Starlette(
    routes=[Mount("/cms", app=cms.app)],
    lifespan=cms.lifespan,
)
```

## Next steps

- **[Field Types](guides/field-types.md)** — all 11 field types with examples
- **[Singletons](guides/singletons.md)** — one-active-at-a-time config documents
- **[Document References](guides/document-references.md)** — link documents together with referential integrity
- **[Testing](guides/testing.md)** — test your blocks with built-in utilities
- **[Webhooks](guides/webhooks.md)** — trigger builds on publish
- **[API Reference](api/cms.md)** — full CMS class and endpoint docs
