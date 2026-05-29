# starlette-cms

Headless CMS for Starlette — block registry, document API, webhooks, and schema versioning.

Part of the [Astraeus](https://github.com/ASneakyToast/astraeus) content stack.

## Install

```bash
pip install starlette-cms
pip install starlette-cms[mcp]      # + MCP server for agent tool use
pip install starlette-cms[postgres] # + Postgres support
```

## Quickstart

```python
from starlette_cms import CMS, TextField, RichTextField, ImageField, ListField
from starlette.applications import Starlette
from starlette.routing import Mount

cms = CMS(database_url="sqlite:///content.db", auth="apikey", api_key="secret")

@cms.block("hero")
class HeroBlock:
    title: str = TextField(required=True, label="Headline")
    body: dict = RichTextField()

@cms.document("page")
class PageDocument:
    title: str = TextField(required=True)
    slug: str = TextField(required=True)
    body: list = ListField(blocks=[HeroBlock])

app = Starlette(routes=[Mount("/cms", app=cms.app)], lifespan=cms.lifespan)
```

## Status

Pre-release. Spec complete, implementation in progress.
