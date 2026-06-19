"""
Piccolo ORM table definitions for starlette-cms.

Tables are defined without a bound engine — the engine is assigned at CMS
init time via ``CMSDatabase.init()``.

Usage::

    from starlette_cms.tables import CMSDocument, CMSMeta
"""

from __future__ import annotations

from piccolo.columns import JSON, Boolean, Text, Timestamptz, Varchar
from piccolo.table import Table


class CMSDocument(Table):
    """Persisted content document."""

    id = Varchar(length=36, primary_key=True)
    doc_type = Varchar(length=255)
    slug = Varchar(length=500)
    body = JSON()
    meta = JSON(default="{}")
    created_at = Timestamptz()
    updated_at = Timestamptz()
    published = Boolean(default=False)
    published_at = Timestamptz(null=True, required=False)
    singleton_status = Varchar(length=16, default="")
    # singleton_status values:
    #   ""         — regular (non-singleton) document, unchanged semantics
    #   "active"   — current published singleton version
    #   "archived" — superseded singleton version
    import_ref = Varchar(length=256, null=True, required=False, index=True)
    # import_ref — stable external ID for gateway-synced documents.
    # Format: "{service}:{subtype}:{external_id}", e.g. "spotify:liked:abc123".
    # NULL for human-authored documents.  Unique per (doc_type, import_ref) pair
    # enforced at the application layer (409 on collision) so that NULL values
    # (authored documents) are permitted without compound-key complexity.


class CMSMeta(Table):
    """Key/value store for CMS-internal metadata (schema_version, etc.)."""

    key = Varchar(length=255, unique=True)
    value = Text()


class CMSWebhook(Table):
    """Registered webhook endpoint."""

    id = Varchar(length=36, primary_key=True)
    url = Text()
    events = JSON()  # ["document.published", ...]
    created_at = Timestamptz()
    active = Boolean(default=True)
