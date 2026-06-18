# API Reference: HTTP Endpoints

All endpoints are mounted under the CMS mount path (default: `/cms`). Paths below are relative to that mount.

## Authentication

Auth behavior depends on the `auth` parameter passed to the CMS constructor:

| Mode | Mutating endpoints | GET endpoints |
|---|---|---|
| `"none"` | Open | Open |
| `"apikey"` | Require `Authorization: Bearer {key}` | Open (unless `read_auth=True`) |
| callable | Require the callable to return `True` | Open (unless `read_auth=True`) |

---

## Documents

### List documents

```
GET /api/documents
```

| Query param | Type | Default | Description |
|---|---|---|---|
| `type` | `str` | — | Filter by document/block type |
| `slug` | `str` | — | Filter by slug |
| `published` | `bool` | — | Filter by publish state |
| `limit` | `int` | `20` | Max results per page |
| `offset` | `int` | `0` | Pagination offset |
| `order_by` | `str` | `created_at` | Sort field: `created_at`, `updated_at`, `published_at`, `slug` |
| `order` | `str` | `desc` | Sort direction: `asc`, `desc` |
| `filters` | `JSON str` | — | Body field filters as JSON object |
| `filter[key]` | `str` | — | Body field filter (bracket syntax) |
| `resolve_refs` | `str` | — | Comma-separated `DocumentRef` field names to inline |

**Response:**

```json
{
  "documents": [
    {
      "id": "abc123",
      "doc_type": "article",
      "slug": "hello-world",
      "body": { ... },
      "meta": {},
      "created_at": "2026-01-15T10:00:00Z",
      "updated_at": "2026-01-15T10:30:00Z",
      "published": true,
      "published_at": "2026-01-15T10:30:00Z"
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

### Create document

```
POST /api/documents
```

**Auth required.**

**Request body:**

```json
{
  "doc_type": "article",
  "slug": "hello-world",
  "body": {
    "title": "Hello World",
    "content": "..."
  },
  "meta": {}
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `doc_type` | `str` | yes | Registered block/document type name |
| `body` | `object` | yes | Document body, validated against the block schema |
| `slug` | `str` | no | URL-friendly identifier |
| `meta` | `object` | no | Arbitrary metadata |

**Response:** `201 Created` with the full document object.

### Get document

```
GET /api/documents/{id}
```

**Response:** The full document object, or `404`.

### Update document

```
PATCH /api/documents/{id}
```

**Auth required.**

**Request body:**

```json
{
  "body": { "title": "Updated Title" },
  "slug": "new-slug",
  "meta": { "reviewed": true }
}
```

All fields are optional. `body` is merged with the existing body. Immutable fields are silently stripped from the update.

**Response:** `200 OK` with the updated document.

### Delete document

```
DELETE /api/documents/{id}
```

**Auth required.**

Enforces referential integrity — if other documents reference this one via `DocumentRef(on_delete="block")`, the delete returns `409 Conflict`.

**Response:** `204 No Content` on success.

### Publish document

```
POST /api/documents/{id}/publish
```

**Auth required.**

Sets `published=true` and `published_at` to the current time. Fires the `document.published` webhook event.

For singleton types, this archives the currently active version first (archive-then-activate).

**Response:** `200 OK` with the updated document.

### Unpublish document

```
POST /api/documents/{id}/unpublish
```

**Auth required.**

Sets `published=false`. Fires the `document.unpublished` webhook event.

**Response:** `200 OK` with the updated document.

---

## Singletons

### Get active singleton

```
GET /api/documents/singleton/{block_type}
```

Returns the currently active singleton document for the given block type.

**Response:** The document object, or `404` if no active singleton exists.

### Publish singleton

```
POST /api/documents/singleton/{block_type}
```

**Auth required.**

Creates a new document, archives the previous active version, and activates the new one.

**Request body:**

```json
{
  "body": { ... },
  "version_message": "Optional description of this version"
}
```

**Response:** `201 Created` with the new active document.

### Singleton history

```
GET /api/documents/singleton/{block_type}/history
```

Returns archived singleton versions, newest first.

**Response:**

```json
{
  "documents": [ ... ],
  "total": 5
}
```

---

## Schema

### List all schemas

```
GET /api/schema
```

Returns JSON Schema for all registered block types.

**Response:**

```json
{
  "hero": {
    "block_type": "hero",
    "schema": { ... },
    "field_meta": {
      "title": { "label": "Headline", "required": true },
      "subtitle": { "label": "Subtitle" }
    }
  }
}
```

### Get one schema

```
GET /api/schema/{block_type}
```

Returns JSON Schema for a single block type, including `field_meta`.

**Response:** `200 OK` with the schema object, or `404` if the block type doesn't exist.

### Schema version

```
GET /api/schema/version
```

No auth required (always open).

**Response:**

```json
{
  "version": "0.4.0"
}
```

---

## Webhooks

### List webhooks

```
GET /api/webhooks
```

**Response:**

```json
{
  "webhooks": [
    {
      "id": "wh_abc123",
      "url": "https://example.com/hook",
      "events": ["document.published"],
      "active": true,
      "created_at": "2026-01-15T10:00:00Z"
    }
  ]
}
```

### Register webhook

```
POST /api/webhooks
```

**Auth required.**

**Request body:**

```json
{
  "url": "https://example.com/hook",
  "events": ["document.published", "document.updated"]
}
```

**Response:** `201 Created` with the webhook object.

### Delete webhook

```
DELETE /api/webhooks/{id}
```

**Auth required.**

**Response:** `204 No Content`.
