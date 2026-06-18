# STORY-005 — Document list filters

**Epic:** [EPIC-001](../EPIC-001-vpp-mvp.md)  
**Status:** Ready  
**Depends on:** STORY-004 (DocumentRef patterns establish body-level filtering needs)  
**Blocks:** Nothing

---

## Goal

Extend `GET /api/documents` to accept a `filters` query parameter that narrows results by
values inside the document `body` JSON. Required for the test case CI runner
(`active=True` filter) and the eval dataset feed (filter by `category`, `score`, etc.).

Also add `order_by` support for deterministic pagination.

---

## Changes required

### `api/documents.py` — `list_documents`

#### Filter parameter

Accept `filters` as a JSON-encoded query string or multiple `filter[key]=value` params.
Support both forms for flexibility:

```
GET /api/documents?type=test_scenario&filters={"active":true}
GET /api/documents?type=test_scenario&filter[active]=true&filter[category]=jewelry
```

Implementation approach — **Python-level filter after DB fetch** (v1):

```python
# Parse filters
raw_filters_json = params.get("filters")
key_value_filters: dict[str, Any] = {}
if raw_filters_json:
    try:
        key_value_filters = json.loads(raw_filters_json)
    except json.JSONDecodeError:
        return JSONResponse({"error": "filters must be valid JSON"}, status_code=400)

# Also support filter[key]=value syntax
for param_name, param_value in params.items():
    if param_name.startswith("filter[") and param_name.endswith("]"):
        key = param_name[7:-1]
        # Coerce strings to Python types
        key_value_filters[key] = _coerce_filter_value(param_value)
```

```python
def _coerce_filter_value(v: str) -> Any:
    """Coerce URL string to bool, int, float, or leave as str."""
    if v.lower() == "true":  return True
    if v.lower() == "false": return False
    try: return int(v)
    except ValueError: pass
    try: return float(v)
    except ValueError: pass
    return v
```

Apply filters to the fetched rows:

```python
def _matches_filters(doc: dict, filters: dict[str, Any]) -> bool:
    body = doc.get("body", {})
    if isinstance(body, str):
        try: body = json.loads(body)
        except: body = {}
    for key, expected in filters.items():
        if body.get(key) != expected:
            return False
    return True
```

After fetching rows from DB (before applying limit/offset for correctness):

```python
if key_value_filters:
    rows = [r for r in all_rows if _matches_filters(_row_to_dict(r), key_value_filters)]
    total = len(rows)
    rows = rows[offset: offset + limit]
```

> **v1 note:** Fetches all rows of the type then filters in Python. Acceptable for < 10k
> documents. Add Piccolo JSON path queries in a follow-on story for production scale.

#### `order_by` parameter

```
GET /api/documents?type=test_scenario&order_by=created_at&order=asc
GET /api/documents?order_by=updated_at&order=desc
```

```python
order_by_field = params.get("order_by", "created_at")
order_asc = params.get("order", "desc").lower() == "asc"

valid_order_fields = {"created_at", "updated_at", "published_at", "slug"}
if order_by_field not in valid_order_fields:
    order_by_field = "created_at"

col = getattr(CMSDocument, order_by_field)
query = query.order_by(col, ascending=order_asc)
```

#### Response shape

Add `filters_applied` to the response for debugging:

```json
{
  "documents": [...],
  "total": 12,
  "filters_applied": {"active": true}
}
```

---

## `cms.documents` Python accessor (STORY-002 extension)

Add `list()` method to `CMSDocuments` (introduced in STORY-002):

```python
class CMSDocuments:
    async def list(
        self,
        block_type: str,
        *,
        filters: dict[str, Any] | None = None,
        published: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        List documents of a given block type with optional body filters.

        Example::

            scenarios = await cms.documents.list(
                "test_scenario",
                filters={"active": True, "category": "jewelry"},
                published=True,
            )
        """
        ...
```

This is the Python-level equivalent of the HTTP filter API, used by CI scripts and
application code that calls the CMS directly (not via HTTP).

---

## Tests

### `tests/test_documents.py` additions

- `test_filter_by_body_field_bool` — `?filters={"active":true}` returns only active docs
- `test_filter_by_body_field_string` — `?filter[category]=jewelry` returns only jewelry
- `test_filter_no_match_returns_empty` — `?filters={"active":false}` on all-true returns []
- `test_filter_combined` — multiple filters AND correctly
- `test_filter_invalid_json` — malformed `filters=` param returns 400
- `test_order_by_created_at_asc` — oldest first
- `test_order_by_updated_at_desc` — newest-updated first (default)
- `test_order_by_invalid_field_falls_back` — unknown field silently uses created_at
- `test_total_reflects_filtered_count` — total in response matches filtered count, not raw count
- `test_cms_documents_list_python_api` — `cms.documents.list()` accessor works

---

## Definition of done

- [ ] `GET /api/documents?filters={...}` filters by body JSON fields
- [ ] `GET /api/documents?filter[key]=value` alternative syntax works
- [ ] Boolean and numeric coercion from URL string params
- [ ] `order_by` and `order` query params supported
- [ ] `total` in response reflects post-filter count
- [ ] `cms.documents.list(block_type, filters={...})` Python accessor
- [ ] All tests above pass
- [ ] No regressions
