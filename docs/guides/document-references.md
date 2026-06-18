# Document References

`DocumentRef` is a typed foreign key between documents. It stores the referenced document's ID, validates on write, and enforces referential integrity on delete.

## Defining a reference

```python
from starlette_cms import CMS, TextField, NumberField, DocumentRef

cms = CMS(database_url="sqlite:///content.db")

@cms.block("submission")
class Submission:
    applicant: str = TextField(required=True)
    amount: float = NumberField(required=True, min_value=0.0)

@cms.block("review")
class Review:
    submission_ref: str = DocumentRef(
        block_type="submission",
        on_delete="block",
        immutable=True,
        label="Submission",
    )
    score: float = NumberField(required=True, min_value=0.0, max_value=100.0)
    notes: str = TextField()
```

## Write-time validation

When you create or update a document with a `DocumentRef` field, the CMS validates that:

1. The referenced document exists
2. The referenced document has the correct `block_type`

If either check fails, the request returns `422`:

```json
{
  "error": "Referenced document not found",
  "field": "submission_ref"
}
```

## `on_delete` semantics

The `on_delete` parameter controls what happens when you try to delete a document that other documents reference:

### `"block"` (default)

The delete is refused. The API returns `409 Conflict`:

```json
{
  "error": "Cannot delete: referenced by 3 document(s)",
  "referencing_count": 3
}
```

### `"nullify"`

The referenced field is set to `None` in all documents that point to the deleted document. The delete proceeds.

### `"cascade"`

All documents that reference the deleted document are also deleted. Use with caution.

## Resolving references in queries

By default, `DocumentRef` fields return just the ID string. Use the `resolve_refs` query parameter to inline the full referenced document:

```bash
# Without resolution — submission_ref is just an ID
curl http://localhost:8000/cms/api/documents?type=review

# With resolution — submission_ref is replaced with the full document
curl "http://localhost:8000/cms/api/documents?type=review&resolve_refs=submission_ref"
```

With `resolve_refs`, the response replaces the ID with the full document object:

```json
{
  "id": "rev_abc",
  "doc_type": "review",
  "body": {
    "submission_ref": {
      "id": "sub_xyz",
      "doc_type": "submission",
      "body": {
        "applicant": "Jane Doe",
        "amount": 50000.0
      }
    },
    "score": 92.5,
    "notes": "Strong application"
  }
}
```

Resolution is O(1) per field — referenced documents are bulk-fetched in a single query.

You can resolve multiple fields by separating them with commas:

```
?resolve_refs=submission_ref,author_ref
```

## Combining with `immutable`

A common pattern is to make references immutable — once a review is linked to a submission, the link can't be changed:

```python
submission_ref: str = DocumentRef(
    block_type="submission",
    on_delete="block",
    immutable=True,
)
```

This prevents accidental re-linking and preserves audit integrity.

## Example: eval dataset

```python
@cms.block("ai_run")
class AIRun:
    model: str = TextField(required=True, immutable=True)
    prompt: str = TextField(required=True, immutable=True)
    output: str = TextField(required=True, immutable=True)

@cms.block("eval_entry")
class EvalEntry:
    run_ref: str = DocumentRef(
        block_type="ai_run",
        on_delete="cascade",
        immutable=True,
    )
    score: float = NumberField(required=True, min_value=0.0, max_value=1.0)
    rationale: str = TextField(required=True)
```

When an AI run is deleted, all its eval entries are automatically cleaned up via `cascade`.
