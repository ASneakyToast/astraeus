# starlette-editor

Visual editing UI for [starlette-cms](../starlette-cms/) — ProseMirror-based rich text, auto-generated form fields, block canvas, and image picker — all driven from your block schema.

Part of the [Astraeus](https://github.com/ASneakyToast/astraeus) content stack.

---

## Install

```bash
pip install starlette-editor
```

## Quickstart

```python
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS
from starlette_editor import Editor

cms = CMS(database_url="sqlite:///./content.db")
editor = Editor(cms=cms, mount_path="/editor")

app = Starlette(
    routes=[
        Mount("/", app=cms.app),
        Mount("/editor", app=editor.app),
    ],
    lifespan=cms.lifespan,
)
```

Editor UI available at: **`/editor/shell`**

---

## Configuration

```python
Editor(
    cms=cms,
    mount_path="/editor",        # where the editor sub-app is mounted (default: /editor)
    media_base="/media",         # optional: mount path of mediakit — enables the image picker
    auth=lambda r: bool(r.user), # optional: callable (request) -> bool protecting /shell
)
```

**Initialization order:** Create the `CMS` instance first, register all blocks, then create `Editor`. `Editor.__init__` registers `/api/editor-schema` on the CMS via `register_extension_route()`.

---

## Auth

Pass any sync or async callable that takes a `Request` and returns `bool`:

```python
# Sync
Editor(cms=cms, auth=lambda r: r.headers.get("X-Admin") == "secret")

# Async
async def require_session(request):
    return await request.session.get("user") is not None

Editor(cms=cms, auth=require_session)
```

Unauthenticated requests to `/shell` receive a `401 Unauthorized` response.

---

## Frontend development

The editor frontend is a bundled vanilla JS application (no framework).
The built artifact at `starlette_editor/static/editor.js` is committed to the repo.

To rebuild after modifying source files in `editor_src/`:

```bash
cd packages/starlette-editor

# Install frontend dependencies (once)
npm ci

# Production build → starlette_editor/static/editor.js
npm run build

# Dev build with inline source maps
npm run build:dev

# JS unit tests
npm test

# Or use make:
make build-frontend
make test-js
```

Source layout:

```
editor_src/
  index.js              ← boot(), buildShell(), DOMContentLoaded handler
  api.js                ← authenticated fetch helpers
  state.js              ← shared state, setState()
  prosemirror/
    markdown.js         ← markdownToPmDoc(), pmDocToMarkdown()
    toolbar.js          ← toolbar command execution and active-state tracking
    mount.js            ← mountProseMirrorEditors(), destroyPmInstances()
  components/
    block-canvas.js     ← ListField / BlockField interactive card canvas
    image-picker.js     ← Mediakit iframe picker widget
    toast.js            ← toast notification system
    confirm.js          ← confirmation dialog
    meta-panel.js       ← document metadata panel
  standard/
    utils.js            ← pure utility functions (humanizeType, docTitle, etc.)
    fields.js           ← fieldWidget() dispatch, buildFieldGroup()
    render.js           ← renderTypeList, renderDocList, renderHeader, renderForm
    actions.js          ← selectType, selectDoc, saveDocument, togglePublish, etc.
```

All ProseMirror packages are bundled from npm — no CDN dependency at runtime.

---

## How it works

1. `Editor.__init__` registers a `/api/editor-schema` endpoint on the CMS.
2. The browser loads `/editor/shell` — a server-rendered HTML page that injects config and loads the JS bundle.
3. `editor.js` boots, fetches `/api/editor-schema`, and auto-generates a form UI from the block schema.
4. CRUD operations go directly to the CMS's own `/api/documents/*` endpoints — the editor is a thin client.

---

## Field type mapping

| Python field class | Editor widget |
|---|---|
| `RichTextField` | ProseMirror rich text editor |
| `TextField` | `<input type="text">` (or `<textarea>` for long-name fields) |
| `ImageField` | Mediakit iframe picker (falls back to text input) |
| `ListField` / `BlockField` | Block canvas with drag-and-drop reorder |
| `SelectField` | `<select>` dropdown |
| `NumberField` | `<input type="number">` with min/max |
| `BoolField` | Toggle switch |
| `DocumentRef` | `<input type="text">` (document ID) |
| `JSONField` | `<textarea>` with JSON pretty-printing |

---

## Status

All implementation phases complete. Self-contained bundle — no CDN dependency.
