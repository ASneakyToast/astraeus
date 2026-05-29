# ADR 001 — UV workspace monorepo vs separate repos

**Status:** Accepted  
**Date:** 2026-05-28

---

## Context

Astraeus consists of three packages (`starlette-cms`, `starlette-editor`, `mediakit`) that are designed to work together but are independently installable. We needed to decide whether to develop them in a single repository or in separate repositories.

`starlette-editor` has a direct dependency on `starlette-cms`. During development, we need to iterate on both simultaneously without publishing to PyPI between changes. `mediakit` is independent but frequently tested alongside the other two.

---

## Decision

Single monorepo using a **UV workspace**, with each package in `packages/{name}/` having its own `pyproject.toml` and publishing independently to PyPI.

```
astraeus/
├── pyproject.toml       ← workspace root (uv.workspace.members = ["packages/*"])
├── uv.lock              ← single lockfile
└── packages/
    ├── starlette-cms/
    ├── starlette-editor/
    └── mediakit/
```

`starlette-editor`'s `pyproject.toml` declares:
```toml
[tool.uv.sources]
starlette-cms = { workspace = true }  # local in dev, PyPI when published
```

---

## Rationale

- **Single lockfile** means all packages always resolve to the same transitive dependency versions — no version skew between packages during development
- **Cross-package local resolution** via `workspace = true` — no `pip install -e .` hacks, no path installs, no `sys.path` manipulation
- **Independent PyPI publishing** — packages are released on their own cadence; versions don't need to stay in lockstep
- **Single CI run** — one test run covers all packages; integration tests across packages work naturally
- **Astraeus brand** — the monorepo is the Astraeus project even though individual packages don't carry the Astraeus name

---

## Alternatives considered

**Separate repos with local path installs during dev**  
Rejected. Managing cross-repo version compatibility is painful and the `pip install -e ../starlette-cms` workflow is fragile.

**Single package with optional sub-modules**  
Rejected. We want `starlette-cms` to be genuinely useful standalone — a user who wants headless CMS without an editor shouldn't install editor dependencies.

**Separate repos with published prereleases**  
Rejected. Publishing a prerelease to PyPI every time you change `starlette-cms` to test in `starlette-editor` is too much friction.

---

## Consequences

- Each package must remain independently buildable — no implicit imports across packages outside the declared dependency graph
- The `examples/demo/pyproject.toml` also uses `workspace = true` sources — it's not publishable, just a dev convenience
- Client sites (like joellithgow.com) are **not** in this monorepo — they're separate repos that consume published packages (or local path overrides during dev)
