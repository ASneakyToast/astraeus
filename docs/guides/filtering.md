# List Filtering & Ordering

The document list endpoint supports filtering by body fields and ordering by standard columns.

## Basic listing

```bash
# All documents
curl http://localhost:8000/cms/api/documents

# Filter by type
curl http://localhost:8000/cms/api/documents?type=article

# Filter by published state
curl http://localhost:8000/cms/api/documents?type=article&published=true

# Pagination
curl http://localhost:8000/cms/api/documents?type=article&limit=10&offset=20
```

## Filtering by body fields

Two syntaxes are available for filtering on fields inside the document body:

### Bracket syntax

The simplest option — add `filter[field]=value` query parameters:

```bash
# Exact match
curl "http://localhost:8000/cms/api/documents?type=task&filter[status]=done"

# Multiple filters (AND)
curl "http://localhost:8000/cms/api/documents?type=task&filter[status]=done&filter[priority]=high"
```

### JSON syntax

For complex filters, pass a JSON object as the `filters` query parameter:

```bash
curl "http://localhost:8000/cms/api/documents?type=task&filters=%7B%22status%22%3A%22done%22%7D"
```

Both syntaxes are equivalent. Bracket syntax is easier for simple cases; JSON syntax works better when values contain special characters.

## Type coercion

Filter values from URL query strings are automatically coerced:

| URL value | Python type |
|---|---|
| `"true"`, `"True"` | `True` |
| `"false"`, `"False"` | `False` |
| `"42"` | `42` (int) |
| `"3.14"` | `3.14` (float) |
| `"hello"` | `"hello"` (str) |

This means `filter[active]=true` correctly matches boolean `True` in the document body, not the string `"true"`.

## Ordering

Control sort order with `order_by` and `order`:

```bash
# Newest first (default)
curl "http://localhost:8000/cms/api/documents?type=article&order_by=created_at&order=desc"

# Alphabetical by slug
curl "http://localhost:8000/cms/api/documents?type=article&order_by=slug&order=asc"

# Most recently updated
curl "http://localhost:8000/cms/api/documents?type=article&order_by=updated_at&order=desc"
```

**Supported `order_by` values:** `created_at`, `updated_at`, `published_at`, `slug`

**Supported `order` values:** `asc`, `desc`

## Response metadata

When filters are applied, the response includes a `filters_applied` key in the metadata:

```json
{
  "documents": [...],
  "total": 5,
  "limit": 20,
  "offset": 0,
  "filters_applied": {
    "status": "done",
    "priority": "high"
  }
}
```

## Python accessor

Use `cms.documents.list()` from application code:

```python
tasks = await cms.documents.list(
    "task",
    filters={"status": "done", "priority": "high"},
    published=True,
    limit=50,
    offset=0,
)
```

## Implementation note

In v1, filtering is done in Python after fetching from the database. This is adequate for small-to-medium datasets. A future version may push filters down to SQL for large-scale use cases.
