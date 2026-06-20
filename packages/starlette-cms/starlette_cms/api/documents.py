"""Document CRUD endpoints — /api/documents"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from piccolo.columns.base import Column
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from starlette_cms.api.webhooks import fire_event
from starlette_cms.auth import require_auth
from starlette_cms.tables import CMSDocument

if TYPE_CHECKING:
    from starlette_cms.app import CMS


def _utcnow() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


def _coerce_filter_value(v: str) -> Any:
    """Coerce URL string to bool, int, float, or leave as str."""
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _matches_filters(doc: dict, filters: dict[str, Any]) -> bool:
    """Return True if all filter key/value pairs match the document body."""
    body = doc.get("body", {})
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            body = {}
    for key, expected in filters.items():
        if body.get(key) != expected:
            return False
    return True


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw Piccolo row dict to a JSON-serialisable document dict."""
    body = row.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            pass

    meta = row.get("meta", "{}")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (json.JSONDecodeError, TypeError):
            meta = {}

    # Convert datetime objects to ISO strings
    result: dict[str, Any] = {}
    for key, value in row.items():
        if key in ("body",):
            result[key] = body
        elif key == "meta":
            result[key] = meta
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


async def _validate_refs(
    cms: CMS, doc_model: Any, body_data: dict[str, Any]
) -> JSONResponse | None:
    """
    For each DocumentRef field in body_data, verify the referenced document exists
    and has the correct block_type. Returns a 422 JSONResponse on failure, None on success.
    """
    ref_fields: dict[str, Any] = getattr(doc_model, "__ref_fields__", {})
    for field_name, ref_descriptor in ref_fields.items():
        ref_id = body_data.get(field_name)
        if ref_id is None:
            continue  # optional ref not provided — skip
        if not isinstance(ref_id, str):
            return JSONResponse(
                {"error": f"{field_name}: DocumentRef must be a string ID"},
                status_code=422,
            )
        # Check existence and type
        rows = (
            await CMSDocument.select(CMSDocument.doc_type)
            .where(CMSDocument.id == ref_id)
            .limit(1)
            .run()
        )
        if not rows:
            return JSONResponse(
                {"error": f"{field_name}: referenced document {ref_id!r} not found"},
                status_code=422,
            )
        if ref_descriptor.block_type and rows[0]["doc_type"] != ref_descriptor.block_type:
            return JSONResponse(
                {
                    "error": (
                        f"{field_name}: expected block_type {ref_descriptor.block_type!r}, "
                        f"got {rows[0]['doc_type']!r}"
                    )
                },
                status_code=422,
            )
    return None


async def _check_ref_integrity(cms: CMS, doc_id: str, doc_type: str) -> JSONResponse | None:
    """
    Scan all registered block/document types for DocumentRef fields pointing at this
    doc_type with on_delete="block". If any referencing documents exist, return 409.
    For on_delete="nullify", set the ref field to None in all referencing documents.
    """
    all_models: list[Any] = list(cms.registry._blocks.values())
    all_models.extend(cms._document_types.values())

    for model in all_models:
        ref_fields: dict[str, Any] = getattr(model, "__ref_fields__", {})
        for field_name, ref_desc in ref_fields.items():
            if ref_desc.block_type != doc_type:
                continue
            if ref_desc.on_delete not in ("block", "nullify", "cascade"):
                continue

            model_doc_type: str = (
                getattr(model, "__document_type__", None)
                or getattr(model, "__block_type__", None)
                or ""
            )
            if not model_doc_type:
                continue

            rows = (
                await CMSDocument.select(CMSDocument.id, CMSDocument.body)
                .where(CMSDocument.doc_type == model_doc_type)
                .run()
            )

            referencing_ids = []
            for row in rows:
                body = row["body"]
                if isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except Exception:
                        body = {}
                if body.get(field_name) == doc_id:
                    referencing_ids.append(row["id"])

            if not referencing_ids:
                continue

            if ref_desc.on_delete == "block":
                return JSONResponse(
                    {"error": f"Cannot delete: referenced by {model_doc_type}.{field_name}"},
                    status_code=409,
                )
            elif ref_desc.on_delete == "nullify":
                for ref_doc_id in referencing_ids:
                    ref_rows = await CMSDocument.select().where(CMSDocument.id == ref_doc_id).run()
                    if not ref_rows:
                        continue
                    ref_body = ref_rows[0]["body"]
                    if isinstance(ref_body, str):
                        try:
                            ref_body = json.loads(ref_body)
                        except Exception:
                            ref_body = {}
                    ref_body[field_name] = None
                    await (
                        CMSDocument.update(
                            {
                                CMSDocument.body: json.dumps(ref_body),
                                CMSDocument.updated_at: datetime.now(UTC),
                            }
                        )
                        .where(CMSDocument.id == ref_doc_id)
                        .run()
                    )
            elif ref_desc.on_delete == "cascade":
                for ref_doc_id in referencing_ids:
                    await CMSDocument.delete().where(CMSDocument.id == ref_doc_id).run()

    return None


async def _bulk_resolve_refs(
    docs: list[dict[str, Any]], resolve_fields: list[str]
) -> list[dict[str, Any]]:
    """
    Bulk-resolve named DocumentRef fields across a list of documents.

    For each field name, issues a single IN query and attaches the resolved
    document dict at ``{field_name}__resolved`` in each document's body.
    """
    for field_name in resolve_fields:
        ids = [
            d["body"].get(field_name)
            for d in docs
            if isinstance(d.get("body"), dict) and d["body"].get(field_name)
        ]
        if not ids:
            continue
        ref_rows = await CMSDocument.select().where(CMSDocument.id.is_in(ids)).run()
        ref_map = {r["id"]: _row_to_dict(r) for r in ref_rows}
        for doc in docs:
            body = doc.get("body")
            if not isinstance(body, dict):
                continue
            ref_id = body.get(field_name)
            if ref_id and ref_id in ref_map:
                body[f"{field_name}__resolved"] = ref_map[ref_id]
    return docs


def make_document_routes(cms: CMS) -> list[Route]:
    """Build and return all document CRUD routes, closed over ``cms``."""

    async def list_documents(request: Request) -> JSONResponse:
        # Read auth only if cms.read_auth is True
        if cms.read_auth:
            if (err := await require_auth(request, cms)) is not None:
                return err

        params = request.query_params
        doc_type = params.get("type")
        slug = params.get("slug")
        import_ref = params.get("import_ref")
        published_param = params.get("published")
        resolve_refs_param = params.get("resolve_refs")
        try:
            limit = int(params.get("limit", 20))
            offset = int(params.get("offset", 0))
        except ValueError:
            return JSONResponse({"error": "limit and offset must be integers"}, status_code=400)

        # --- Filter params ---
        raw_filters_json = params.get("filters")
        key_value_filters: dict[str, Any] = {}
        if raw_filters_json:
            try:
                key_value_filters = json.loads(raw_filters_json)
            except json.JSONDecodeError:
                return JSONResponse({"error": "filters must be valid JSON"}, status_code=400)

        for param_name, param_value in params.items():
            if param_name.startswith("filter[") and param_name.endswith("]"):
                key = param_name[7:-1]
                key_value_filters[key] = _coerce_filter_value(param_value)

        # --- Order params ---
        order_by_field = params.get("order_by", "created_at")
        order_asc = params.get("order", "desc").lower() == "asc"

        valid_order_fields = {"created_at", "updated_at", "published_at", "slug"}
        if order_by_field not in valid_order_fields:
            order_by_field = "created_at"

        order_col = getattr(CMSDocument, order_by_field)

        query = CMSDocument.select()

        if doc_type:
            query = query.where(CMSDocument.doc_type == doc_type)
        if slug:
            query = query.where(CMSDocument.slug == slug)
        if import_ref is not None:
            query = query.where(CMSDocument.import_ref == import_ref)
        if published_param is not None:
            published = published_param.lower() in ("true", "1", "yes")
            query = query.where(CMSDocument.published == published)

        query = query.order_by(order_col, ascending=order_asc)

        if key_value_filters:
            all_rows = await query.run()
            all_docs = [_row_to_dict(r) for r in all_rows]
            filtered_docs = [d for d in all_docs if _matches_filters(d, key_value_filters)]
            total = len(filtered_docs)
            docs = filtered_docs[offset : offset + limit]
        else:
            # Total count (without limit/offset)
            count_query = CMSDocument.count()
            if doc_type:
                count_query = count_query.where(CMSDocument.doc_type == doc_type)
            if slug:
                count_query = count_query.where(CMSDocument.slug == slug)
            if import_ref is not None:
                count_query = count_query.where(CMSDocument.import_ref == import_ref)
            if published_param is not None:
                count_query = count_query.where(CMSDocument.published == published)  # type: ignore[possibly-undefined]

            total = await count_query.run()
            rows = await query.limit(limit).offset(offset).run()
            docs = [_row_to_dict(r) for r in rows]

        # Bulk-resolve requested ref fields
        if resolve_refs_param:
            resolve_fields = [f.strip() for f in resolve_refs_param.split(",") if f.strip()]
            docs = await _bulk_resolve_refs(docs, resolve_fields)

        return JSONResponse(
            {
                "documents": docs,
                "total": total,
                "filters_applied": key_value_filters,
            }
        )

    async def create_document(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        doc_type = data.get("doc_type")
        if not doc_type:
            return JSONResponse({"error": "doc_type is required"}, status_code=422)

        # Look up the model — check document types first, then block registry as
        # fallback (used for @cms.block(append_only=True) and singleton types).
        doc_model = cms._document_types.get(doc_type)
        if doc_model is None:
            if doc_type in cms.registry:
                doc_model = cms.registry.get(doc_type)
            else:
                return JSONResponse(
                    {"error": f"Unknown document type: {doc_type!r}"},
                    status_code=422,
                )

        body_data = data.get("body", {})
        try:
            validated = doc_model.model_validate(body_data)
        except ValidationError as exc:
            return JSONResponse(
                {"error": "Validation failed", "detail": exc.errors()},
                status_code=422,
            )

        # Validate ImageField values against the configured media backend
        if cms.media_backend is not None:
            image_fields = getattr(doc_model, "__image_fields__", [])
            validated_dump = validated.model_dump()
            for fname in image_fields:
                val = validated_dump.get(fname)
                if val and not await cms.media_backend.confirm_exists(val):
                    return JSONResponse(
                        {"error": "Image key not found", "field": fname},
                        status_code=422,
                    )

        # Validate DocumentRef fields
        if (err := await _validate_refs(cms, doc_model, validated.model_dump())) is not None:
            return err

        from nanoid import generate

        doc_id = generate(size=21)
        slug = data.get("slug", "")
        import_ref: str | None = data.get("import_ref") or None
        doc_meta = data.get("meta", {})
        now = datetime.now(UTC)

        # 409 on duplicate (doc_type, import_ref) — NULL import_refs are never deduplicated
        if import_ref is not None:
            existing = (
                await CMSDocument.select(CMSDocument.id)
                .where(
                    CMSDocument.doc_type == doc_type,
                    CMSDocument.import_ref == import_ref,
                )
                .limit(1)
                .run()
            )
            if existing:
                return JSONResponse(
                    {
                        "error": "Duplicate import_ref",
                        "detail": (
                            f"A document of type {doc_type!r} with "
                            f"import_ref {import_ref!r} already exists."
                        ),
                        "existing_id": existing[0]["id"],
                    },
                    status_code=409,
                )

        # append_only=True: create and publish atomically (ADR 014)
        is_append_only = False
        try:
            is_append_only = cms.registry.is_append_only(doc_type)
        except Exception:
            pass

        if is_append_only:
            await CMSDocument.insert(
                CMSDocument(
                    id=doc_id,
                    doc_type=doc_type,
                    slug=slug,
                    body=json.dumps(validated.model_dump(exclude_none=True)),
                    meta=json.dumps(doc_meta),
                    created_at=now,
                    updated_at=now,
                    published=True,
                    published_at=now,
                    import_ref=import_ref,
                )
            ).run()
        else:
            await CMSDocument.insert(
                CMSDocument(
                    id=doc_id,
                    doc_type=doc_type,
                    slug=slug,
                    body=json.dumps(validated.model_dump(exclude_none=True)),
                    meta=json.dumps(doc_meta),
                    created_at=now,
                    updated_at=now,
                    published=False,
                    published_at=None,
                    import_ref=import_ref,
                )
            ).run()

        rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()

        loop = asyncio.get_running_loop()
        extra: dict[str, Any] = {}
        if is_append_only:
            extra["append_only"] = True
        loop.create_task(fire_event(cms, "document.created", doc_id, doc_type, slug, extra=extra))

        return JSONResponse(_row_to_dict(rows[0]), status_code=201)

    async def get_document(request: Request) -> JSONResponse:
        if cms.read_auth:
            if (err := await require_auth(request, cms)) is not None:
                return err

        doc_id = request.path_params["id"]
        rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()
        if not rows:
            return JSONResponse({"error": "Document not found"}, status_code=404)
        return JSONResponse(_row_to_dict(rows[0]))

    async def patch_document(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        doc_id = request.path_params["id"]
        rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()
        if not rows:
            return JSONResponse({"error": "Document not found"}, status_code=404)

        row = rows[0]
        doc_type = row["doc_type"]

        # append_only=True: PATCH is not allowed (ADR 014)
        try:
            if cms.registry.is_append_only(doc_type):
                return JSONResponse(
                    {"error": "append_only documents cannot be modified"},
                    status_code=405,
                )
        except Exception:
            pass

        try:
            patch_data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
        doc_model = cms._document_types.get(doc_type)
        if doc_model is None and doc_type in cms.registry:
            doc_model = cms.registry.get(doc_type)

        # Merge body
        existing_body = row.get("body", "{}")
        if isinstance(existing_body, str):
            try:
                existing_body = json.loads(existing_body)
            except Exception:
                existing_body = {}

        new_body_data = patch_data.get("body", {})

        # Strip immutable fields before merge — silently drop, no error (ADR 013).
        if doc_model is not None:
            for field_name in getattr(doc_model, "__immutable_fields__", []):
                new_body_data.pop(field_name, None)

        merged_body = {**existing_body, **new_body_data}

        # Validate merged body if we have a model
        if doc_model is not None:
            try:
                validated = doc_model.model_validate(merged_body)
                # exclude_none=True: absent optional fields are omitted from storage.
                # A field explicitly set to null in the PATCH body is preserved as null
                # (intentional clear), per ADR 016.
                merged_body = validated.model_dump(exclude_none=True)
            except ValidationError as exc:
                return JSONResponse(
                    {"error": "Validation failed", "detail": exc.errors()},
                    status_code=422,
                )

            # Validate ImageField values against the configured media backend
            if cms.media_backend is not None:
                image_fields = getattr(doc_model, "__image_fields__", [])
                for fname in image_fields:
                    val = merged_body.get(fname)
                    if val and not await cms.media_backend.confirm_exists(val):
                        return JSONResponse(
                            {"error": "Image key not found", "field": fname},
                            status_code=422,
                        )

            # Validate DocumentRef fields in the patched data
            if (err := await _validate_refs(cms, doc_model, new_body_data)) is not None:
                return err

        update_kwargs: dict[Column | str, Any] = {
            CMSDocument.body: json.dumps(merged_body),
            CMSDocument.updated_at: datetime.now(UTC),
        }

        if "slug" in patch_data:
            update_kwargs[CMSDocument.slug] = patch_data["slug"]

        if "import_ref" in patch_data:
            new_import_ref: str | None = patch_data["import_ref"] or None
            update_kwargs[CMSDocument.import_ref] = new_import_ref

        if "meta" in patch_data:
            existing_meta = row.get("meta", "{}")
            if isinstance(existing_meta, str):
                try:
                    existing_meta = json.loads(existing_meta)
                except Exception:
                    existing_meta = {}
            merged_meta = {**existing_meta, **patch_data["meta"]}
            update_kwargs[CMSDocument.meta] = json.dumps(merged_meta)

        await CMSDocument.update(update_kwargs).where(CMSDocument.id == doc_id).run()

        updated_rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()
        updated_row = updated_rows[0]

        loop = asyncio.get_running_loop()
        loop.create_task(
            fire_event(cms, "document.updated", doc_id, doc_type, updated_row.get("slug", ""))
        )

        return JSONResponse(_row_to_dict(updated_row))

    async def delete_document(request: Request) -> Response:
        if (err := await require_auth(request, cms)) is not None:
            return err  # type: ignore[return-value]

        doc_id = request.path_params["id"]
        rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()
        if not rows:
            return JSONResponse({"error": "Document not found"}, status_code=404)

        row = rows[0]
        doc_type = row["doc_type"]
        slug = row.get("slug", "")

        # append_only=True: DELETE is not allowed (ADR 014)
        try:
            if cms.registry.is_append_only(doc_type):
                return JSONResponse(
                    {"error": "append_only documents cannot be deleted"},
                    status_code=405,
                )
        except Exception:
            pass

        # Enforce referential integrity (on_delete="block" → 409; "nullify" → set to None)
        if (err := await _check_ref_integrity(cms, doc_id, doc_type)) is not None:
            return err  # type: ignore[return-value]

        await CMSDocument.delete().where(CMSDocument.id == doc_id).run()

        loop = asyncio.get_running_loop()
        loop.create_task(fire_event(cms, "document.deleted", doc_id, doc_type, slug))

        return Response(status_code=204)

    async def publish_document(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        doc_id = request.path_params["id"]
        rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()
        if not rows:
            return JSONResponse({"error": "Document not found"}, status_code=404)

        row = rows[0]
        doc_type = row["doc_type"]
        now = datetime.now(UTC)

        # Singleton enforcement — archive the currently active document first
        is_singleton = False
        try:
            is_singleton = cms.registry.is_singleton(doc_type)
        except Exception:
            pass

        if is_singleton:
            await (
                CMSDocument.update({CMSDocument.singleton_status: "archived"})
                .where(
                    CMSDocument.doc_type == doc_type,
                    CMSDocument.singleton_status == "active",
                )
                .run()
            )
            await (
                CMSDocument.update(
                    {
                        CMSDocument.published: True,
                        CMSDocument.published_at: now,
                        CMSDocument.singleton_status: "active",
                        CMSDocument.updated_at: now,
                    }
                )
                .where(CMSDocument.id == doc_id)
                .run()
            )
        else:
            await (
                CMSDocument.update(
                    {
                        CMSDocument.published: True,
                        CMSDocument.published_at: now,
                        CMSDocument.updated_at: now,
                    }
                )
                .where(CMSDocument.id == doc_id)
                .run()
            )

        updated_rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()
        updated_row = updated_rows[0]

        extra: dict[str, Any] = {}
        if is_singleton:
            extra["singleton"] = True

        loop = asyncio.get_running_loop()
        loop.create_task(
            fire_event(
                cms,
                "document.published",
                doc_id,
                updated_row["doc_type"],
                updated_row.get("slug", ""),
                extra=extra,
            )
        )

        return JSONResponse(_row_to_dict(updated_row))

    async def unpublish_document(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        doc_id = request.path_params["id"]
        rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()
        if not rows:
            return JSONResponse({"error": "Document not found"}, status_code=404)

        now = datetime.now(UTC)
        await (
            CMSDocument.update(
                {
                    CMSDocument.published: False,
                    CMSDocument.updated_at: now,
                }
            )
            .where(CMSDocument.id == doc_id)
            .run()
        )

        updated_rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()
        updated_row = updated_rows[0]

        loop = asyncio.get_running_loop()
        loop.create_task(
            fire_event(
                cms,
                "document.unpublished",
                doc_id,
                updated_row["doc_type"],
                updated_row.get("slug", ""),
            )
        )

        return JSONResponse(_row_to_dict(updated_row))

    async def get_singleton(request: Request) -> JSONResponse:
        """Return the currently active singleton for a block type, or 404."""
        if cms.read_auth:
            if (err := await require_auth(request, cms)) is not None:
                return err

        block_type = request.path_params["block_type"]

        rows = await (
            CMSDocument.select()
            .where(
                CMSDocument.doc_type == block_type,
                CMSDocument.singleton_status == "active",
            )
            .limit(1)
            .run()
        )
        if not rows:
            return JSONResponse(
                {"error": f"No published singleton for {block_type!r}"},
                status_code=404,
            )
        return JSONResponse(_row_to_dict(rows[0]))

    async def publish_singleton(request: Request) -> JSONResponse:
        """Create and publish a singleton document in a single step (for seed scripts)."""
        if (err := await require_auth(request, cms)) is not None:
            return err

        block_type = request.path_params["block_type"]

        if block_type not in cms.registry:
            return JSONResponse(
                {"error": f"Unknown block type: {block_type!r}"},
                status_code=422,
            )
        if not cms.registry.is_singleton(block_type):
            return JSONResponse(
                {"error": f"Block type {block_type!r} is not a singleton"},
                status_code=422,
            )

        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        body_data = data.get("body", {})
        version_message = data.get("version_message", "")

        block_model = cms.registry.get(block_type)
        try:
            validated = block_model.model_validate(body_data)
        except ValidationError as exc:
            return JSONResponse(
                {"error": "Validation failed", "detail": exc.errors()},
                status_code=422,
            )

        from nanoid import generate

        doc_id = generate(size=21)
        now = datetime.now(UTC)
        doc_meta: dict[str, Any] = {}
        if version_message:
            doc_meta["version_message"] = version_message

        await (
            CMSDocument.update({CMSDocument.singleton_status: "archived"})
            .where(
                CMSDocument.doc_type == block_type,
                CMSDocument.singleton_status == "active",
            )
            .run()
        )

        await CMSDocument.insert(
            CMSDocument(
                id=doc_id,
                doc_type=block_type,
                slug="",
                body=json.dumps(validated.model_dump(exclude_none=True)),
                meta=json.dumps(doc_meta),
                created_at=now,
                updated_at=now,
                published=True,
                published_at=now,
                singleton_status="active",
            )
        ).run()

        rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()
        new_doc = _row_to_dict(rows[0])

        loop = asyncio.get_running_loop()
        loop.create_task(
            fire_event(
                cms,
                "document.published",
                doc_id,
                block_type,
                "",
                extra={"singleton": True},
            )
        )

        return JSONResponse(new_doc, status_code=201)

    async def get_singleton_history(request: Request) -> JSONResponse:
        """Return archived versions of a singleton, newest first."""
        if cms.read_auth:
            if (err := await require_auth(request, cms)) is not None:
                return err

        block_type = request.path_params["block_type"]

        rows = await (
            CMSDocument.select()
            .where(
                CMSDocument.doc_type == block_type,
                CMSDocument.singleton_status == "archived",
            )
            .order_by(CMSDocument.published_at, ascending=False)
            .run()
        )
        return JSONResponse({"history": [_row_to_dict(r) for r in rows]})

    return [
        Route("/api/documents", endpoint=list_documents, methods=["GET"]),
        Route("/api/documents", endpoint=create_document, methods=["POST"]),
        Route(
            "/api/documents/singleton/{block_type}",
            endpoint=get_singleton,
            methods=["GET"],
        ),
        Route(
            "/api/documents/singleton/{block_type}",
            endpoint=publish_singleton,
            methods=["POST"],
        ),
        Route(
            "/api/documents/singleton/{block_type}/history",
            endpoint=get_singleton_history,
            methods=["GET"],
        ),
        Route("/api/documents/{id}", endpoint=get_document, methods=["GET"]),
        Route("/api/documents/{id}", endpoint=patch_document, methods=["PATCH"]),
        Route("/api/documents/{id}", endpoint=delete_document, methods=["DELETE"]),
        Route("/api/documents/{id}/publish", endpoint=publish_document, methods=["POST"]),
        Route("/api/documents/{id}/unpublish", endpoint=unpublish_document, methods=["POST"]),
    ]
