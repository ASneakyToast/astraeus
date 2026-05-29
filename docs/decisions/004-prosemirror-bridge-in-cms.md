# ADR 004 — ProseMirrorBridge owned by starlette-cms, activated by editor

**Status:** Accepted  
**Date:** 2026-05-28

---

## Context

`starlette-editor` needs to serve a ProseMirror-compatible schema definition at `/api/editor-schema`. This schema is derived from the CMS block registry — it must understand block field types, nesting, and metadata.

The question is: where does the bridge logic live?

- In `starlette-editor`, which imports and introspects CMS internals
- In `starlette-cms` as an optional module that the editor activates

---

## Decision

`starlette_cms/prosemirror/` is present in the `starlette-cms` package. It contains `ProseMirrorBridge` — the class that derives a ProseMirror schema from a `BlockRegistry`.

The module has no runtime effect unless explicitly instantiated. `starlette-editor` imports it and activates it:

```python
# starlette_editor/app.py
from starlette_cms.prosemirror import ProseMirrorBridge

class Editor:
    def __init__(self, cms):
        self.bridge = ProseMirrorBridge(cms.registry)
        cms.register_extension_route("/api/editor-schema", self.bridge.schema_endpoint, ...)
```

---

## Rationale

The bridge logic requires **deep knowledge of block model internals** — it needs to know how `ListField`, `BlockField`, and `RichTextField` map to ProseMirror node types. That knowledge lives in `starlette-cms`. Putting the bridge logic in `starlette-editor` would require either:

- Importing CMS internals from the editor (tight coupling, brittle)
- Duplicating the field-type knowledge in the editor (divergence over time)

Owning the bridge in `starlette-cms` keeps field-type semantics in one place. The editor's role is narrow: activate the bridge, register the endpoint, and consume the output.

**The `starlette-cms` package pays zero runtime cost** when the bridge isn't activated. The `prosemirror/` module is a stub until `ProseMirrorBridge(registry)` is called — at which point it's only instantiated because the editor was explicitly mounted.

---

## Consequences

- `starlette-cms` has ProseMirror knowledge baked in — this is intentional and correct
- The `/api/editor-schema` response format is versioned by `starlette-cms`, not `starlette-editor`. `starlette-editor` declares a minimum CMS version for schema format compatibility
- This is also the correct foundation for collaborative editing (North Star): the step validation logic must live on the server side, which means in `starlette-cms`. The bridge is a natural extension point for that future work
