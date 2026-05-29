# Astraeus — Agent Instructions

This is the Astraeus monorepo. Read this file before doing anything else.

---

## What this repo is

**Astraeus** is an open-source content stack for Python/Starlette developers. Three packages:

- **`starlette-cms`** — headless CMS (block registry, document API, webhooks, schema versioning)
- **`starlette-editor`** — visual editing UI (ProseMirror-based, auto-generated from block schema)
- **`mediakit`** — media management (S3-compatible storage, IIIF Image API, presigned uploads)

Each package is independently installable from PyPI. Together they form a full content management stack.

**Why it exists:** Joel needed an agentic content backend for his personal site (joellithgow.com) and future client work. He wanted something he could use across projects — not a one-off backend. The agentic layer (MCP servers) is a first-class design goal, not a bolt-on.

---

## Before writing any code

1. Read `docs/architecture.md` — full system diagram and package relationships
2. Read `docs/roadmap.md` — phased implementation plan, what's done, what's next
3. Read the relevant ADR(s) in `docs/decisions/` for the area you're working in
4. Check the relevant package's `README.md` and the original spec in `/Users/jlithgow/Desktop/Personal/personal-starlette-plugins/` (not in this repo, but Joel has it locally)

---

## Repo structure

```
astraeus/
├── CLAUDE.md                      ← you are here
├── pyproject.toml                 ← UV workspace root (no package here)
├── uv.lock                        ← single lockfile for all packages
├── .python-version                ← 3.12
├── packages/
│   ├── starlette-cms/             ← implement first, everything depends on it
│   ├── starlette-editor/          ← implements after starlette-cms Phase 1
│   └── mediakit/                  ← mostly independent, parallels starlette-cms
├── docs/
│   ├── architecture.md            ← system design and package relationships
│   ├── roadmap.md                 ← phased implementation plan
│   └── decisions/                 ← ADRs (numbered, immutable once written)
└── examples/
    └── demo/                      ← minimal full-stack integration example
```

---

## Development workflow

```bash
# Install everything
uv sync

# Run all tests
uv run pytest packages/

# Run one package's tests
uv run pytest packages/starlette-cms/

# Type check
uv run pyright packages/starlette-cms/

# Lint
uv run ruff check packages/
uv run ruff format packages/
```

---

## Conventions

### Code style
- Python 3.12+, type annotations everywhere
- Pydantic v2 for all data models
- `from __future__ import annotations` at the top of every file
- Async-first — all I/O is async
- Match the docstring style already in the codebase (brief summary, `::` code examples)

### Package boundaries
- `starlette-editor` depends on `starlette-cms` — never the reverse
- `mediakit` has no dependency on either CMS package
- `starlette-cms` has an optional soft dependency on `mediakit` via the `MediaBackend` protocol — it never imports mediakit directly

### Testing
- Every public function gets a test
- Use `starlette_cms.testing.RegistryTestCase` for tests that need a CMS instance — never share state between tests
- `httpx.AsyncClient` with `transport=ASGITransport(app=cms.app)` for HTTP endpoint tests

### Commits
- Conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `chore:`
- End commit messages with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## Current status

See `docs/roadmap.md` for the full phased plan and current progress.

**Short version:** Scaffold is complete. No implementation has started. `starlette-cms` Phase 1 is the correct next step — it unblocks everything else.

---

## Key decisions already made (don't relitigate)

- UV workspace monorepo — one lockfile, packages publish independently to PyPI
- starlette-cms is headless-first — no built-in admin UI
- Plugin composition via `register_extension_route()` — editor extends CMS, not peer coupling
- MCP servers are optional HTTP client wrappers (`[mcp]` extra), not embedded in package core
- Webhooks handle build triggers — no direct Netlify/Vercel integration
- Content-addressed storage keys in mediakit (`originals/{sha256_prefix}/{filename}`)
- Two-form block decorator: `@cms.block()` (immediate) vs `@block()` (deferred/standalone)

See `docs/decisions/` for the full rationale on each.

---

## Joel's personal site

The first real consumer of these packages is `github.com/ASneakyToast/joellithgow` — an Astro.js site currently using MDX files for content. The migration path is:

1. Deploy a starlette-cms + mediakit backend
2. Update the Astro site to fetch from the CMS at build time
3. Register a Netlify webhook so publish events trigger rebuilds
4. Configure the MCP servers so Joel can update content via Claude Code

The personal site lives in its own repo and is **not** in this monorepo. During development, it points at the local workspace packages via `[tool.uv.sources]`.
