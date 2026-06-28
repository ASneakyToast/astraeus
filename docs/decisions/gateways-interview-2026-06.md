# starlette-cms-gateways — Product Interview Notes
**Date:** 2026-06-19 to 2026-06-28
**Interviewer:** Claude
**Subject:** Joel Lithgow

---

## Deployment & Timeline

- **Current:** EC2 instance, SQLite, staging/prototype — not yet production
- **Future:** Self-hosted hardware eventually, but EC2 for the foreseeable future
- **DB:** SQLite, staying that way — no Postgres, no Redis, no queue infrastructure
- **Timeline:** No hard deadline. Correctness and completeness of the framework matters more than speed to ship

---

## First Gateways

Three concrete use cases in priority order:

1. **Spotify** — joellithgow.com (liked songs / listening activity)
2. **iNaturalist** — joellithgow.com (nature observations)
3. **GitHub** — `~/code/work/internal-tools/lzr-skills` (releases/activity; theoretical but concrete
   enough to design for; also the entry point for bringing lzr-skills onto Astraeus)

All three are time-based polling gateways. GitHub is the first webhook-triggered candidate.

---

## Display & UX Intent

- All synced items arrive as **drafts** (`published=False`) by default
- Joel is always the human gate for publishing — nothing goes live without explicit review
- After sync, Joel (or an LLM via MCP, or the editor UI) annotates/curates and publishes
- **Configurable per gateway class** whether items auto-publish or stay as drafts — some gateways
  (or other consumers) may want auto-publish
- Synced items should be **annotatable after creation** — `append_only=True` is wrong for this use case

---

## Framework Gaps to Address

1. **`append_only=True` on gateway blocks is wrong** — blocks must be mutable so annotations can be
   added post-sync
2. **Auto-publish config missing** — gateway class needs a field (e.g. `auto_publish: bool = False`)
   controlling whether synced documents land as drafts or go live immediately
3. **Trigger types not implemented** — framework needs three built-in trigger modes: `time-based`,
   `webhook`, `manual`. Currently only CLI manual exists
4. **Webhook trigger needs a Starlette endpoint** — fires subprocess `gateways sync <name>`, returns
   200 immediately (fire-and-forget, no queue)
5. **Failure webhook not implemented** — optional configurable webhook on sync failure; consistent with
   how the rest of the framework handles extensibility
6. **GatewaySyncState should be dropped** — OTEL is the observability layer; per-gateway state tracking
   is the gateway's own business if needed
7. **`since` is not a framework primitive** — each gateway owns its own fetch logic and
   cursor/timestamp management internally; the framework doesn't prescribe time-based filtering
8. **OTel (ADR 017) not yet implemented** — accepted but not built; gateway sync errors need structured
   logging + spans before any of this goes to production

---

## Open Decisions (resolved during interview)

1. **Webhook trigger subprocess model** — confirmed: Starlette endpoint fires `gateways sync` as a
   subprocess, fire-and-forget, OTEL covers observability. No retry infrastructure needed given SQLite
   constraint.
2. **`append_only` default** — should be `False` (mutable) for gateway blocks. Per-gateway override is
   fine if a consumer explicitly wants immutable audit records.
3. **Built-in migration registration** — worth an ADR eventually (it's a sound pattern, Django/Piccolo
   both do it), but not blocking now. Park for when there are multiple consumers.

---

## Prioritised Next Actions

1. **Fix `append_only=True`** — make gateway blocks mutable by default; add opt-in immutable flag for
   audit-style gateways
2. **Add `auto_publish` config to gateway class** — `False` by default; all synced items land as drafts
3. **Drop `GatewaySyncState`** — remove the framework primitive; update tests and docs accordingly
4. **Remove `since` as a framework primitive** — simplify `fetch()` contract; each gateway handles its
   own cursor/timestamp internally
5. **Implement OTel (ADR 017)** — structlog + opentelemetry-api in library packages; `astraeus-otel`
   bootstrap package; replace all silent swallows in gateways CLI
6. **Implement three trigger types** — `time-based` (cron-friendly CLI), `webhook` (Starlette endpoint
   → subprocess), `manual` (existing CLI, formalise it)
7. **Optional failure webhook** — configurable on the gateway class; fires on sync error with structured
   payload
8. **Build Spotify gateway** — in joellithgow repo, first real consumer; validates the full framework
   stack
9. **Build iNaturalist gateway** — second consumer; confirms the pattern generalises
10. **Build GitHub gateway (theoretical)** — first webhook-triggered gateway; entry point for lzr-skills
    onto Astraeus

---

## Constraints for Future Agents

- **SQLite only, no queue infrastructure** — no Redis, no Postgres, no arq/procrastinate. Any design
  that requires a queue backend is out of scope.
- **`since` is not a framework primitive** — do not add it back. Gateways own their fetch logic.
- **`GatewaySyncState` is removed** — do not reference or rebuild it.
- **Draft-by-default is the model** — `published=False` on all synced documents unless
  `auto_publish=True` on the gateway class.
- **OTel is the observability layer** — do not add custom logging infrastructure; implement ADR 017
  instead.
- **Trigger types are an enum on the gateway class** — `time-based`, `webhook`, `manual`; the
  framework provides the plumbing for all three.
- **Built-in migration registration is deferred** — do not implement it until there are multiple real
  consumers.
- **`append_only` defaults to `False`** — gateway blocks are mutable. Immutable is opt-in.
