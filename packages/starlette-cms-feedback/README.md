# starlette-cms-feedback

Feedback and bug reports for a [starlette-cms](https://github.com/ASneakyToast/astraeus) instance — file,
list and triage reports from an admin page, an HTTP API, or MCP tools.

Part of the [Astraeus](https://github.com/ASneakyToast/astraeus) data platform for Python/Starlette developers.

## Install

```bash
pip install starlette-cms-feedback
pip install "starlette-cms-feedback[mcp]"   # MCP server tools
```

## Quickstart

```python
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS
from starlette_cms_feedback import FeedbackAdmin

cms = CMS(database_url="sqlite:///content.db", auth="apikey", api_key="secret")
feedback = FeedbackAdmin(cms=cms, db_path="/var/lib/myapp/feedback.db")

app = Starlette(
    routes=[
        Mount("/cms", app=cms.app),
        Mount("/feedback", app=feedback.app),
    ],
    lifespan=cms.lifespan,
)
```

Construct `FeedbackAdmin` before first touching `cms.app` — it registers its API routes on the CMS.

The admin page is at `/feedback/shell`. With `astraeus-portal`'s `compose_app(..., feedback=feedback)` it
also gets a card on the portal.

## API

Registered on the CMS, so they sit under its mount path (`/cms/api/feedback` above). **Every route requires
CMS auth, reads included.**

| Route | Purpose |
|-------|---------|
| `GET /api/feedback` | List, newest first. Filters: `status`, `kind`, `component`, `limit`, `offset` |
| `POST /api/feedback` | File a report; it starts as `new` |
| `GET /api/feedback/{id}` | One report |
| `PATCH /api/feedback/{id}` | Triage: `status`, `severity`, `triage_notes` |

A report is what the reporter said (`kind`, `title`, `description`, `component`, `severity`,
`steps_to_reproduce`, `expected`, `actual`, `environment`, `reporter`) plus triage state (`status`,
`triage_notes`). Only triage state changes after filing.

Statuses: `new`, `triaged`, `in_progress`, `fixed`, `wontfix`.
Kinds: `bug`, `feedback`, `idea`. Severities: `low`, `medium`, `high`, `blocking`.

## MCP

```python
from starlette_cms_feedback.mcp.server import build_feedback_mcp_server

server = build_feedback_mcp_server(base_url="https://mysite.com/cms", api_key="secret")
server.run(transport="stdio")
```

Tools: `file_feedback`, `list_feedback`, `get_feedback`, `triage_feedback`.

## Why not CMS documents?

The CMS document API is public-read by default and has no draft/published gate on reads, so a report stored
as a document would be readable by anyone unless the CMS runs with `read_auth=True`. Reports live in their
own SQLite file instead and are only reachable through the auth-checked routes above. You give up document
version history and editor visibility.
