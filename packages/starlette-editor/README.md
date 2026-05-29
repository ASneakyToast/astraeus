# starlette-editor

Visual editing UI for starlette-cms — ProseMirror-based, auto-generated from your block schema.

Part of the [Astraeus](https://github.com/ASneakyToast/astraeus) content stack.

## Install

```bash
pip install starlette-editor
```

## Quickstart

```python
from starlette_cms import CMS
from starlette_editor import Editor

cms = CMS(...)
editor = Editor(cms=cms)  # zero config — auto-generates UI from block schema

app = Starlette(
    routes=[Mount("/cms", app=cms.app), Mount("/editor", app=editor.app)],
    lifespan=cms.lifespan,
)
# Editor at: /editor/shell
```

## Status

Pre-release. Spec complete, implementation in progress.
