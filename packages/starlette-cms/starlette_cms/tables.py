"""
Piccolo ORM table definitions for starlette-cms.

Tables are defined without a bound engine — the engine is assigned at CMS
init time via ``CMSDatabase.init()``.

Usage::

    from starlette_cms.tables import CMSDocument, CMSMeta
"""

from __future__ import annotations

from piccolo.columns import JSON, Boolean, Integer, Text, Timestamptz, Varchar
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
    draft_body = JSON(null=True, required=False, default=None)
    # draft_body — working draft (unpublished edits). NULL means no unpublished
    # edits exist; non-NULL means the document has unsaved changes not yet in body.
    draft_deleted = Boolean(null=True, required=False, default=None)
    # draft_deleted — pending deletion staged via the editor.
    # None/False = no pending delete; True = will delete when changeset publishes.
    # Cleared on discard-draft.
    draft_published = Boolean(null=True, required=False, default=None)
    # draft_published — pending publish state change.
    # None = no pending change; True = will publish; False = will unpublish.
    # Applied when the changeset publishes; cleared on discard-draft.
    draft_version = Integer(default=0)
    # draft_version — incremented on every PATCH that writes to draft_body.
    # Reset to 0 on publish or discard-draft.


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


class CMSDocumentVersion(Table):
    """Snapshot of a document body at publish or revert time.

    One row per publish/revert event. The composite index on
    (document_id, version) should be created manually after migration:
        CREATE INDEX IF NOT EXISTS idx_cms_document_version_doc_ver
            ON cms_document_version (document_id, version);
    """

    document_id = Varchar(length=36, index=True)
    version = Integer()
    body = JSON()
    action = Varchar(length=16)  # "publish" | "revert"
    changeset_id = Varchar(length=36, null=True, required=False)
    created_at = Timestamptz()


class CMSChangeset(Table):
    """A named group of documents for atomic publish."""

    id = Varchar(length=36, primary_key=True)
    title = Varchar(length=500, default="")
    status = Varchar(length=16, default="open")  # "open" | "review" | "published" | "scheduled" | "reverted"
    created_at = Timestamptz()
    publish_at = Timestamptz(null=True, required=False)
    # publish_at — NULL = not scheduled
    published_at = Timestamptz(null=True, required=False)
    # published_at — NULL = not yet published
    reviewed_at = Timestamptz(null=True, required=False)
    # reviewed_at — set when changeset enters 'review' status


class CMSChangesetDocument(Table):
    """Join table: which documents belong to which changeset."""

    changeset_id = Varchar(length=36)
    document_id = Varchar(length=36)
    added_at = Timestamptz()
    # composite primary key enforced at application layer (409 on duplicate)


class CMSStep(Table):
    """Persisted ProseMirror collab step for history and rewind.

    One row per accepted step. The composite index on (document_id, version)
    should be created manually after migration:
        CREATE INDEX IF NOT EXISTS idx_cms_step_doc_version
            ON cms_step (document_id, version);
    """

    # Piccolo adds a Serial ``id`` auto-increment primary key automatically
    # when no column is marked primary_key=True.
    document_id = Varchar(length=36, index=True)
    client_id = Varchar(length=36)
    version = Integer()  # version number AFTER this step is applied
    step_data = Text()   # JSON-serialised ProseMirror step object
    created_at = Timestamptz()
