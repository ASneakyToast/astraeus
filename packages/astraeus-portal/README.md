# astraeus-portal

Central navigation hub (portal) for Astraeus — discover and navigate all admin
interfaces from one page.

Part of the [Astraeus](https://github.com/ASneakyToast/astraeus) content stack.

---

## Install

```bash
pip install astraeus-portal
```

With the optional compose shortcut:

```bash
pip install astraeus-portal[compose]
```

---

## Usage

### Standalone portal

```python
from starlette.applications import Starlette
from starlette.routing import Mount
from astraeus_portal import Portal, PortalApp

portal = Portal(
    apps=[
        PortalApp(
            name="Editor",
            path="/editor/shell",
            description="Create and edit content documents",
            icon="✏️",
        ),
        PortalApp(
            name="Media",
            path="/media/admin",
            description="Browse, upload, and manage media assets",
            icon="🖼️",
        ),
        PortalApp(
            name="Gateways",
            path="/gateways/shell",
            description="Sync data from external services",
            icon="🔄",
        ),
        PortalApp(
            name="Chat",
            path="/chat/shell",
            description="AI-powered editing assistant",
            icon="💬",
        ),
    ]
)

app = Starlette(
    routes=[
        Mount("/cms", app=cms.app),
        Mount("/editor", app=editor.app),
        Mount("/", app=portal.app),  # portal at root
    ],
    lifespan=cms.lifespan,
)
```

### Composed app (auto-wires everything)

```python
from astraeus_portal import compose_app

app = compose_app(
    cms=cms,
    editor=editor,
    media=media,
    chat=chat,
    gateways=gateway_admin,
    docs_url="https://github.com/ASneakyToast/astraeus#readme",
    github_url="https://github.com/ASneakyToast/astraeus",
)
```

This mounts everything at conventional paths and adds the portal at `/`
with auto-populated app cards. Lifespans are composed automatically.

Visit `http://localhost:8000/` to see the portal.

---

## PortalApp fields

| Field        | Required | Description                                      |
|-------------|----------|--------------------------------------------------|
| `name`       | Yes      | Human-readable app name (e.g. "Editor")          |
| `path`       | Yes      | URL to the app's shell page (e.g. `/editor/shell`) |
| `description`| No       | One-line description shown on the card            |
| `icon`       | No       | Emoji or icon character                           |
| `tags`       | No       | List of tag strings for categorization            |

---

## Auth

Pass a callable to protect the portal page:

```python
Portal(apps=apps, auth=lambda r: r.headers.get("X-Admin") == "secret")
```

Unauthenticated visitors are redirected to the login path.

---

## Development

```bash
# Install
uv sync --package astraeus-portal

# Run tests
uv run pytest packages/astraeus-portal/

# Type check
uv run pyright packages/astraeus-portal/

# Lint
uv run ruff check packages/astraeus-portal/
```

---

## Status

Alpha — 0.1.0