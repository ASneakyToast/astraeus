# Singleton Documents

A **singleton** is a block type where only one version is active at a time. Use singletons for configuration, settings, rate tables — anything where you want version history but only one "current" value.

## Defining a singleton

Pass `singleton=True` to the block decorator:

```python
from starlette_cms import CMS, NumberField, BoolField, TextField

cms = CMS(database_url="sqlite:///content.db")

@cms.block("site_config", singleton=True)
class SiteConfig:
    site_name: str = TextField(required=True, label="Site Name")
    maintenance_mode: bool = BoolField(default=False)
    max_upload_mb: float = NumberField(default=10.0, min_value=1.0)
```

## How publishing works

Singletons use **archive-then-activate** semantics:

1. When you publish a new version, the currently active version is archived
2. The new version becomes the sole active document
3. Archived versions remain in the database as history

Only one document of a singleton type can have `singleton_status = "active"` at any time.

## API endpoints

### Get the active singleton

```
GET /api/documents/singleton/{block_type}
```

```bash
curl http://localhost:8000/cms/api/documents/singleton/site_config
```

Returns the currently active document, or `404` if none has been published yet.

### Publish a new version

```
POST /api/documents/singleton/{block_type}
```

```bash
curl -X POST http://localhost:8000/cms/api/documents/singleton/site_config \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer secret" \
  -d '{
    "body": {
      "site_name": "My Site",
      "maintenance_mode": false,
      "max_upload_mb": 25.0
    },
    "version_message": "Increased upload limit"
  }'
```

This creates a new document, archives the previous active version, and activates the new one — all atomically.

### View history

```
GET /api/documents/singleton/{block_type}/history
```

```bash
curl http://localhost:8000/cms/api/documents/singleton/site_config/history
```

Returns archived versions ordered newest-first.

## Python accessor

Access the active singleton from application code:

```python
config = await cms.documents.get_singleton("site_config")
print(config["body"]["site_name"])
```

Raises `DocumentNotFound` if no active singleton exists.

## Example: governed rate configuration

```python
@cms.block("underwriting_rates", singleton=True)
class UnderwritingRates:
    base_rate: float = NumberField(required=True, min_value=0.0, precision=4)
    risk_multiplier: float = NumberField(required=True, min_value=1.0, precision=2)
    max_coverage: float = NumberField(required=True, min_value=0.0)
    effective_date: str = TextField(required=True, label="Effective Date")
```

Each time rates change, a new version is published. The previous rates remain in history for audit purposes. Downstream consumers always read from the active singleton — they never see stale data.

## Webhooks

Singleton publishes fire the `document.published` webhook event with an additional `"singleton": true` field in the payload:

```json
{
  "event": "document.published",
  "document_id": "abc123",
  "document_type": "underwriting_rates",
  "slug": null,
  "timestamp": "2026-01-15T10:30:00Z",
  "singleton": true
}
```
