# Astraeus — Agent Instructions

This is the Astraeus monorepo. Read this file before doing anything else.

---

## What this repo is

**Astraeus** is a governed data platform for Python/Starlette developers. Three packages:

- **`starlette-cms`** — headless CMS (block registry, document API, webhooks, schema versioning)
- **`starlette-editor`** — visual editing UI (ProseMirror-based, auto-generated from block schema)
- **`mediakit`** — media management (S3-compatible storage, IIIF Image API, presigned uploads)

Each package is independently installable from PyPI. Together they form a full content management and data governance stack.

**Why it exists:** Joel needed an agentic content backend for his personal site (joellithgow.com) and future client work. He wanted something he could use across projects — not a one-off backend. The agentic layer (MCP servers) is a first-class design goal, not a bolt-on.

**What it turned out to be:** Through real-world use, Astraeus has proven useful well beyond editorial content. Any structured data artifact that needs version history, authorship, approval workflow, and audit trail is a natural fit — intake forms, actuarial rule tables, AI pipeline prompts, eval datasets, curated test cases. The same primitives (blocks, documents, singletons, references, webhooks) serve all of these. See `docs/use-cases/` for worked examples.

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

**Short version:** Phases 0–6 complete (including EPIC-001 VPP MVP primitives and ADR 014). starlette-cms core, schema versioning, webhooks, testing utilities, new field types, singletons, immutable fields, DocumentRef, list filters, and MCP server are all working. mediakit core is complete: storage backend, catalog, upload flow, processing pipeline (EXIF strip, WebP conversion, dimension cap), IIIF Image API Level 1, asset routes, references routes, and auth. Phase 7 (mediakit admin UI) is next.

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

## Use cases

See `docs/use-cases/` for the full set of worked examples. These are not just illustrations — they
directly inform roadmap priorities and surface new primitives.

**Primary (original design driver):**
- [`personal-site-joellithgow.md`](docs/use-cases/personal-site-joellithgow.md) — agent-driven publishing for joellithgow.com; drives MCP server, webhook→build trigger, editor auto-generation

**Extended (discovered through real-world application):**
- [`vpp-underwriting-intake.md`](docs/use-cases/vpp-underwriting-intake.md) — structured intake forms as governed documents
- [`vpp-rule-governance.md`](docs/use-cases/vpp-rule-governance.md) — actuarial rule tables as singleton governed config
- [`vpp-eval-dataset.md`](docs/use-cases/vpp-eval-dataset.md) — human-scored AI runs as documents with references
- [`vpp-test-case-library.md`](docs/use-cases/vpp-test-case-library.md) — curated test scenarios as authored fixtures
- [`vpp-prompt-versioning.md`](docs/use-cases/vpp-prompt-versioning.md) — AI pipeline prompts as versioned governed config

**Joel's personal site** (`github.com/ASneakyToast/joellithgow`) lives in its own repo and is **not** in this monorepo. During development it points at local workspace packages via `[tool.uv.sources]`.
