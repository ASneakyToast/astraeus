# ADR 006 — Webhooks for build triggers, not direct Netlify/Vercel integration

**Status:** Accepted  
**Date:** 2026-05-28

---

## Context

A key use case for Astraeus is powering a statically-built frontend (Astro, Next.js static export, etc.) where the frontend rebuilds when content is published. The CMS needs to notify the frontend host when content changes.

Netlify and Vercel both expose build hooks — URLs that trigger a rebuild when POSTed to. The question is how tightly to integrate with them.

---

## Decision

`starlette-cms` ships a **generic webhook system**. Users register a URL and a list of events. When those events occur, the CMS fires a POST to the registered URL with a standard payload.

There is no Netlify-specific or Vercel-specific integration. A Netlify build hook is just a webhook URL that happens to trigger a rebuild when POSTed to.

**Usage:**
```
POST /api/webhooks
{
  "url": "https://api.netlify.com/build_hooks/abc123",
  "events": ["document.published"]
}
```

That's it. No Netlify SDK, no Vercel adapter, no special config.

---

## Rationale

**Netlify build hooks already speak HTTP POST.** A generic webhook that fires on `document.published` is all that's needed. Netlify-specific integration would add a dependency (or at least specific knowledge) for zero additional benefit.

**Generic webhooks are infinitely more useful.** The same system can notify:
- Netlify and Vercel rebuild hooks
- A custom revalidation endpoint on a Next.js app
- A Slack webhook for content notifications
- Any custom automation

**The agent's job is to publish, not to build.** The agent calls `publish_document`. The webhook fires. Netlify rebuilds. This is the correct separation — the agent should not know or care about the deployment infrastructure.

**Fire-and-forget is fine for v1.** Build hooks are idempotent — if a webhook fires twice, the site just rebuilds twice. No retry queue needed until there's evidence of delivery failures at scale.

---

## Alternatives considered

**First-class Netlify integration (Netlify SDK, deploy previews, etc.)**  
Rejected. Vendor lock-in, extra dependency, and no benefit over a generic POST.

**Direct rebuild trigger in the CMS code (hardcoded URL env var)**  
Rejected. Inflexible, not reusable across projects. The webhook system is only marginally more code and is infinitely more general.

---

## Consequences

- v1 webhooks are fire-and-forget. If delivery fails (network error, build hook returns 500), it's silently dropped. A future `cms_webhook_log` table with retry queue is the v2 upgrade path.
- Users must register their webhook URL after deploying the CMS. This is a one-time setup step, documented in the README.
- Multiple webhooks can be registered for the same event — useful for notifying multiple services simultaneously
