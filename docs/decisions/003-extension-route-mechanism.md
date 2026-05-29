# ADR 003 — Plugin composition via register_extension_route()

**Status:** Accepted  
**Date:** 2026-05-28

---

## Context

`starlette-editor` needs to add a route to the CMS sub-application: `/api/editor-schema`. This route serves the ProseMirror schema definition derived from the CMS block registry — it must live on the CMS sub-application (so the browser calls it at the same origin as the CMS API) but its logic belongs to the editor.

Options:
1. Put the route in `starlette-cms` as a first-party endpoint
2. Have the editor mount its own sub-application with the endpoint (different path)
3. Give the CMS a registration mechanism for companion packages to add routes

---

## Decision

`CMS` exposes `register_extension_route(path, endpoint, methods, name)`. Any package can call this before `cms.app` is first accessed to add routes to the CMS sub-application.

`starlette-editor` calls this at `Editor.__init__` time to register `/api/editor-schema`.

The CMS has no conditional logic for editor presence. It simply builds whatever routes have been registered.

---

## Rationale

**Option 1 (first-party route in CMS) rejected:** The CMS would need to know about `starlette-editor` and import from it, or have editor-specific logic baked in. This breaks the clean layering — the editor is supposed to be a plugin, not a built-in.

**Option 2 (editor mounts its own sub-app) rejected:** `/api/editor-schema` must live on the CMS mount to avoid cross-origin issues in the browser. The browser loads the editor from `/editor/shell` and calls `/cms/api/editor-schema` — if editor-schema were at `/editor/api/editor-schema`, the CMS and editor would need to share CORS config explicitly.

**Option 3 (extension routes) chosen:** The CMS is a passive host. Any package can add routes to it. The CMS doesn't know or care what those routes do. `starlette-editor` registers its route and the CMS builds it. If the editor is never constructed, the route never exists — no dead routes, no null-checks.

---

## Consequences

- Extension routes must be registered before `cms.app` is first accessed. The initialization order is: `CMS(...)` → `Editor(cms=cms)` → `Starlette(routes=[Mount("/cms", cms.app)])`. This is documented and enforced (calling `register_extension_route` after app access raises `RuntimeError`).
- Future companion packages (analytics, search, preview) can use the same mechanism without changes to `starlette-cms`
- The CMS's `cms.app` lazy property is a deliberate design — it gives plugins a window to register before the app is finalized
