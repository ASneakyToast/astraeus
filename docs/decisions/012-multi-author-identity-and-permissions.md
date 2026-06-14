# ADR 012 — Multi-author identity and permission resolution

**Status:** Proposed  
**Date:** 2026-06-13

---

## Context

The current auth system answers a single question: **is this request allowed?**

```python
# Current auth callable signature
async def auth(request: Request) -> bool
```

The CMS has no concept of *who* made a request — only whether it was permitted. This means:

- `cms_documents` has no `created_by` or `updated_by` columns — no audit trail
- All authenticated users have identical permissions — an editor can delete documents, an
  admin can't do anything an editor can't
- There is no way to express "users can only edit their own documents"

For single-author deployments (personal site, MCP agent with an API key) this is fine. For
multi-author use cases — a CMS shared by multiple editors, a governed data platform where
different teams own different document types — it is a real gap.

---

## Decision

Add two optional hooks to `CMS(...)`:

### 1. `identity` callable

```python
async def identity(request: Request) -> Any | None
```

Called after `auth` passes. Returns a user object (any type — the CMS treats it as opaque)
or `None` if no identity can be determined. The returned object is:
- Stored as `str(user)` in `created_by` / `updated_by` on the document row
- Passed as-is to the `permission` callable

Recommended return type is `starlette.authentication.BaseUser` (e.g. `SimpleUser(username)`)
since Starlette's auth ecosystem uses it, but the CMS accepts any object.

### 2. `permission` callable

```python
async def permission(
    request: Request,
    user: Any | None,
    operation: str,
    document: dict | None,
) -> bool
```

Called on every mutating operation after `auth` passes. `operation` is one of:
`"create"`, `"update"`, `"delete"`, `"publish"`, `"unpublish"`.
`document` is the current document row (as a dict) for update/delete/publish/unpublish, or
`None` for create.

If not set, all authenticated requests are permitted — identical to current behaviour.

### 3. `created_by` and `updated_by` columns

`cms_documents` gains two nullable string columns:
- `created_by` — set at create time from `str(user)` if `identity` is configured
- `updated_by` — updated on every write from `str(user)` if `identity` is configured

These are nullable so existing deployments without an `identity` hook are unaffected.

---

## Rationale

### Separation of concerns

Three distinct questions, three distinct hooks:

| Hook | Question |
|---|---|
| `auth` | Is this a legitimate client? (API key, session, etc.) |
| `identity` | Who specifically is it? |
| `permission` | Can this identity do this specific thing? |

Combining them (e.g. making `auth` return a user object) conflates gating with identification.
Keeping them separate means each is independently optional and independently testable.

### Full backward compatibility

`identity` and `permission` are both optional. A CMS configured with only `auth=` behaves
exactly as today — no code changes required for existing deployments.

### Opaque user type

The CMS stores `str(user)` and passes the user object through to the `permission` callable —
it never inspects the user's fields. This means the identity system is decoupled from any
specific user model. Kratos, JWT claims, a custom session store, a simple username string —
all work without changes to the CMS.

### `document` passed to permission resolver

Many real permission patterns depend on the document being operated on:
- "Users can only edit their own documents" → `document["created_by"] == str(user)`
- "Only admins can delete published documents" → `document["published"] and user.role == "admin"`

Passing `None` for create (the document doesn't exist yet) is an intentional signal — create
permissions are often role-based rather than ownership-based.

---

## Example: Kratos-backed multi-author CMS

```python
import httpx
from starlette.authentication import SimpleUser
from starlette_cms import CMS

async def auth(request):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "http://kratos:4433/sessions/whoami",
            cookies=request.cookies,
        )
        return resp.status_code == 200

async def identity(request):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "http://kratos:4433/sessions/whoami",
            cookies=request.cookies,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return SimpleUser(data["identity"]["traits"]["email"])

async def permission(request, user, operation, document):
    # Admins can do anything
    if getattr(user, "is_admin", False):
        return True
    # Editors can create and update their own documents, but not delete or publish
    if operation in ("create", "update"):
        if operation == "update" and document:
            return document.get("created_by") == str(user)
        return True
    return False

cms = CMS(
    database_url="sqlite:///content.db",
    auth=auth,
    identity=identity,
    permission=permission,
)
```

---

## Alternatives considered

**Make `auth` return a user object instead of bool**  
Breaking change — every existing `auth` callable would need to be updated. The auth
and identity concerns are also distinct: a valid API key has no "identity" in the
human-user sense. Rejected.

**Rely on Starlette's `AuthenticationMiddleware`**  
Starlette has a built-in `AuthenticationMiddleware` that populates `request.user`.
The CMS could simply read `request.user` from the scope. Rejected because:
(1) it requires the host to configure middleware and understand ASGI scope propagation,
(2) the CMS currently controls auth entirely within each endpoint — mixing two auth
patterns would be confusing, (3) it provides identity but no permission hook.
That said, an `identity` callable that reads `request.user` is trivially compatible:
`identity=lambda req: req.user if req.user.is_authenticated else None`.

**Per-document-type permission rules**  
An earlier sketch considered permission rules declared on `@cms.document(...)` directly.
Rejected because it embeds policy in schema — permission rules change more often than
document schemas, and the callable hook gives the host full flexibility without any
framework opinion on policy structure.

---

## Consequences

- `CMS.__init__` gains two new optional keyword arguments: `identity` and `permission`
- `cms_documents` table gains `created_by TEXT` and `updated_by TEXT` nullable columns —
  this is a schema migration; existing deployments will have `NULL` in both columns
- Every mutating endpoint handler gains a `permission` check after `auth` passes
- `GET /api/documents` response includes `created_by` and `updated_by` fields when present
- The `auth` callable interface is **unchanged** — fully backward compatible
- `read_auth=True` applies to the `auth` check only; `permission` is only invoked on mutations
- For the personal site and single-author deployments: configure neither hook, behaviour is identical to today

## Implementation phase

This is a **Phase 4+** change — it requires a schema migration and touches every endpoint.
The `identity` and `permission` parameters should be wired into `CMS.__init__` and the
`check_auth` / `require_auth` functions in `auth.py` before any multi-author use case is built.
