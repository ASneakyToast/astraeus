# ADR 005 — MCP servers as optional HTTP client wrappers, not embedded

**Status:** Accepted  
**Date:** 2026-05-28

---

## Context

Both `starlette-cms` and `mediakit` need an agent interface — a way for an LLM (via Claude Code, Claude Desktop, or similar) to create, edit, and manage content using tools.

Options:
1. Embed MCP server logic directly in each package's core
2. Build a separate `astraeus-mcp` package that wraps both APIs
3. Add an optional `[mcp]` extra to each package — a thin HTTP client that exposes the existing API as MCP tools

---

## Decision

Each package ships an optional MCP server as an `[mcp]` extra. The MCP server is a **thin HTTP client** of the package's own existing API — it contains no business logic, only tool definitions and HTTP calls.

```bash
pip install starlette-cms[mcp]
starlette-cms mcp serve --url https://mysite.com/cms --api-key secret

pip install mediakit[mcp]
mediakit mcp serve --url https://mysite.com/media --api-key secret
```

The MCP server runs as a local process. It talks to the deployed backend over HTTP. It does not need to run on the same machine as the server.

---

## Rationale

**The existing HTTP API is already the right interface.** The CMS API is clean, authenticated, and well-defined. An MCP tool that calls `POST /api/documents` is functionally identical to the editor calling the same endpoint. No special agent pathway is needed in the CMS itself.

**MCP server as a separate process is correct.** Claude Code and Claude Desktop expect to launch MCP servers as processes that communicate over stdio or SSE. Embedding the MCP server in the CMS process would require running both the CMS and the MCP server together — wrong architecture. The MCP server is a client, not a co-process.

**`[mcp]` as an optional extra keeps the core lean.** Users who don't use agent tooling don't install `mcp` as a dependency. The core package has no awareness of MCP.

**Runs locally against a remote server.** You can deploy the CMS to Fly.io and run the MCP server on your laptop, pointing at the live URL. This is actually ideal — the agent tools run in your local environment (where Claude Code runs) while the data lives in a deployed backend.

---

## Alternatives considered

**Embed MCP in the running CMS server**  
Rejected. MCP servers communicate over stdio/SSE as a separate process. Embedding creates architectural confusion and would require the deployed CMS to accept MCP connections — a different security surface than the API key–protected HTTP API.

**Single `astraeus-mcp` package wrapping both APIs**  
Considered. Pro: one install, one command. Con: couples the release cycle of CMS and Mediakit MCP servers; a consumer using only one package would install dependencies for both. The independent `[mcp]` extras scale better.

---

## Consequences

- MCP tool implementations are HTTP calls — they're very simple to write and easy to test (just mock the HTTP responses)
- Tool names and descriptions must be agent-legible — good descriptions are more important than they'd be in a typical API
- The MCP server must handle auth correctly: `Authorization: Bearer {key}` on every mutating request
- Future: if both MCP servers are commonly used together, a convenience `astraeus mcp serve` that launches both as a composed server is a reasonable v2 addition
