# ADR 009 — Singleton documents for governed configuration

**Status:** Proposed  
**Date:** 2026-06-13  
**Informed by:** `docs/use-cases/vpp-rule-governance.md`

---

## Context

starlette-cms models content as documents — instances of a block type stored in a collection and
queryable as a list. This covers editorial use cases well (many blog posts, many products, many
submissions).

A second class of use cases has emerged from exploring structured intake and rules governance
(see `docs/use-cases/vpp-rule-governance.md`): **governed configuration**. Examples:

- Actuarial rate tables (storage rates → annual premium multipliers)
- Decision thresholds (scheduled coverage ceiling, manual review floor)
- Category parameters (high-value threshold, GIA requirement per item type)
- Feature flags, pricing tiers, any system-wide setting with an approval lifecycle

These share a key property: there is exactly one authoritative published value at any time.
They are not a list of items — they are a single source of truth with version history.

Currently, starlette-cms has no way to model this. A developer could create a block type and
enforce "only ever create one document" manually, but that's not a concept the framework
understands or enforces — the admin UI would still show a list view, `documents.list()` would
still be the read path, and nothing would prevent a second published document.

The question: should starlette-cms add `singleton=True` as a first-class block modifier, or
is this better handled outside the CMS (e.g., the application layer enforces single-document
semantics by convention)?

---

## Decision

**Accept `singleton=True` as a first-class block modifier on `@block()` and `@cms.block()`.**

Singleton blocks differ from regular blocks in three ways:

1. **Read path** — `cms.documents.get_singleton(block_type)` returns the current published
   document directly (not a paginated list). Raises `NotFound` if no published document exists.

2. **Publish semantics** — publishing a new version of a singleton automatically archives the
   previous published document. "Multiple published" is a state violation — the API rejects it.

3. **Admin UI hint** — starlette-editor renders singleton blocks as a settings panel (single
   form, save/publish buttons) rather than a document list + create button.

The block registry stores `singleton: bool` on each `BlockRegistration`. The document API
enforces singleton semantics at the persistence layer, not just the application layer.

---

## API shape

```python
# Definition
@cms.block("storage_rates", singleton=True)
class StorageRates:
    bank_vault: NumberField(label="Bank Vault Rate", precision=4, default=0.005)
    home_safe:  NumberField(label="Home Safe Rate",  precision=4, default=0.010)
    # ...

# Read (application layer)
rates = await cms.documents.get_singleton("storage_rates")
rate  = rates.data["bank_vault"]

# Write (usually via admin UI or seed script)
await cms.documents.publish_singleton("storage_rates", {
    "bank_vault": 0.004,
    "home_safe":  0.010,
    # ...
}, version_message="Q3 actuary review — vault penetration down")

# Audit
history = await cms.documents.get_singleton_history("storage_rates")
# returns list of archived versions, newest first
```

---

## Rejected alternatives

**1. Convention-based (application enforces one document):**  
The application could call `documents.list("storage_rates")` and use `[0]`. Simple, requires
no framework changes. Rejected because: the admin UI would allow creating multiple documents,
there's no enforced publish semantics, and the intent is invisible to future developers and
agents working in the codebase. Correctness by convention is weaker than correctness by design.

**2. Separate `config` API alongside `documents`:**  
A distinct `cms.config.get("storage_rates")` / `cms.config.set(...)` surface. Rejected because:
it duplicates the document lifecycle (draft, publish, version history, webhooks) that already
exists and works. Config objects benefit from the same governed lifecycle as content documents —
splitting into a separate API means maintaining two parallel systems.

**3. Environment variables / external config files:**  
Already the status quo in usaa-vpp. The problem this ADR solves is exactly the lack of
governance, auditability, and approval workflow that env vars and Python constants cannot provide.
Rejected as not solving the problem.

---

## Consequences

**Positive:**
- Governed configuration becomes a first-class Astraeus use case alongside editorial content and
  structured intake
- The same admin UI, webhook system, and version history work for config objects
- Application code reads `get_singleton()` once at boot + cache-invalidates on webhook — simple
  and deterministic
- Satisfies compliance/audit requirements: every threshold change is timestamped, attributed, and
  permanent in the version archive

**Negative / tradeoffs:**
- `singleton=True` is a new concept the block registry must understand — adds surface area
- Seed scripts are required to establish the initial published document when deploying to a new
  environment; there is no automatic default
- The "singleton" term is borrowed from ORM patterns but means something slightly different here
  (one published document, many archived versions) — documentation must be clear

**Neutral / deferred:**
- Whether singletons can be "unpublished" (returned to draft) is deferred. The initial
  implementation treats any published singleton as permanent — you publish a new version over it,
  never unpublish. This matches the intent of governed configuration.
- Admin UI for singletons (settings panel vs. list view) is an starlette-editor concern, deferred
  to editor Phase 2.

---

## Implementation notes

- `BlockRegistration` gains `singleton: bool = False`
- Document persistence layer adds a uniqueness constraint: at most one document with
  `(block_type, status="published")` when `singleton=True`
- `publish_singleton()` wraps the existing publish + archive in a transaction
- `get_singleton()` is a thin wrapper over a filtered `documents.list()` with `.first()` +
  `NotFound` on empty — no new persistence logic needed
- Webhook payload for singleton publish includes `"singleton": true` so consumers can distinguish
  config-reload events from content-publish events
