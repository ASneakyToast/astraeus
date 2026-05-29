# ADR 002 — Headless-first: no built-in admin UI in starlette-cms

**Status:** Accepted  
**Date:** 2026-05-28

---

## Context

Most CMS frameworks bundle an admin interface with the content layer. This creates coupling — the admin UI assumptions shape the data model, auth requirements, and routing structure. It also means every project using the CMS gets an admin UI they may not want, can't easily replace, and has to maintain.

---

## Decision

`starlette-cms` ships with **no admin UI**. It is a pure data and API layer. The visual editing interface is provided by the separate `starlette-editor` package, which is optional and has no privileged access to CMS internals.

---

## Rationale

- **starlette-cms is genuinely useful without an editor.** An Astro frontend fetching from the CMS API at build time doesn't need a visual editor — it needs a reliable JSON API and a webhook system.
- **The editor can't pollute the data layer.** If the editor is a separate package that only touches the CMS via its public API, editor concerns (form layout, toolbar config, UI state) can never creep into the block schema or document model.
- **Projects can build custom editors.** `starlette-editor` exposes `EditorContext` — the same building blocks as the StandardEditor — so teams with specific UI requirements can build bespoke interfaces without forking the CMS.
- **Smaller core.** A project that only needs the CMS doesn't install ProseMirror, the editor JS bundle, or any template engine. `pip install starlette-cms` is a lean install.
- **The agent IS an editor.** With the MCP server, an LLM agent can create and publish content. For personal sites and small projects, the agent interface may be sufficient — no visual editor required at all.

---

## Alternatives considered

**Bundle a minimal admin UI in starlette-cms itself**  
Rejected. Even "minimal" UIs grow. The first request for a feature (bulk operations, live preview, media picker) starts the coupling spiral.

**Make starlette-editor a required dependency**  
Rejected. This defeats headless-first and forces editor dependencies on every consumer.

---

## Consequences

- `starlette-cms` must have a clean, stable public API that `starlette-editor` and agent tools can consume as clients — there is no shortcut of reaching into CMS internals
- Documentation must include examples of headless usage (Astro fetching at build time) alongside editor usage — the headless path is first-class, not a footnote
- The `/api/schema` endpoint is important for non-editor consumers (agent tools, code generation, custom UIs) — it must be well-designed and documented
