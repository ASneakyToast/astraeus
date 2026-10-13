# starlette-cms-feedback — Agent Instructions

Read `../../CLAUDE.md` (the root Astraeus instructions) before working in this package.

## What this package is

Feedback and bug reports for a starlette-cms instance: a `FeedbackAdmin` (admin page + API routes
registered on the CMS) and an optional MCP server. Same shape as `starlette-cms-gateways`.

```
src/starlette_cms_feedback/
├── models.py       # enums + Pydantic models (FeedbackCreate, FeedbackUpdate, FeedbackReport)
├── store.py        # FeedbackStore — SQLite via asyncio.to_thread
├── api.py          # extension routes on the CMS: /api/feedback[/{id}]
├── admin/          # FeedbackAdmin + the HTML shell
└── mcp/server.py   # build_feedback_mcp_server() [requires mcp extra]
```

## Critical constraints

**Reports are not CMS documents, on purpose.** `GET /api/documents` is public-read by default and does
not gate drafts, so a document-backed report would be world-readable. Reports live in `FeedbackStore`
and are served only by routes that call `require_auth` — reads included. Do not add an unauthenticated
read path, and do not move storage into the document table without making the CMS's `read_auth` a
hard requirement.

**Reporter text is untrusted.** The shell builds its DOM with `textContent` only. Never use
`innerHTML` for report fields.

**Only triage fields change after filing.** `FeedbackUpdate` is deliberately limited to `status`,
`severity` and `triage_notes`; the reporter's words are not rewritten.

**MCP stays a thin HTTP wrapper** (ADR 005) — no store access, no business logic.

## Development

```bash
uv sync --all-packages
uv run pytest packages/starlette-cms-feedback/
uv run ruff check packages/starlette-cms-feedback/
uv run pyright packages/starlette-cms-feedback/
```
