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
        published_param = params.get("published")
        try:
            limit = int(params.get("limit", 20))
            offset = int(params.get("offset", 0))
        except ValueError:
            return JSONResponse({"error": "limit and offset must be integers"}, status_code=400)

        query = CMSDocument.select()

        if doc_type:
            query = query.where(CMSDocument.doc_type == doc_type)
        if slug:
            query = query.where(CMSDocument.slug == slug)
        if published_param is not None:
            published = published_param.lower() in ("true", "1", "yes")
            query = query.where(CMSDocument.published == published)

        # Total count (without limit/offset)
        count_query = CMSDocument.count()
        if doc_type:
            count_query = count_query.where(CMSDocument.doc_type == doc_type)
        if slug:
            count_query = count_query.where(CMSDocument.slug == slug)
        if published_param is not None:
            count_query = count_query.where(CMSDocument.published == published)  # type: ignore[possibly-undefined]

        total = await count_query.run()
        rows = await (
            query.limit(limit)
            .offset(offset)
            .order_by(CMSDocument.created_at, ascending=False)
            .run()
        )

        return JSONResponse(
            {
                "documents": [_row_to_dict(r) for r in rows],
                "total": total,
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

        doc_model = cms._document_types.get(doc_type)
        if doc_model is None:
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

        from nanoid import generate

        doc_id = generate(size=21)
        slug = data.get("slug", "")
        doc_meta = data.get("meta", {})

        await CMSDocument.insert(
            CMSDocument(
                id=doc_id,
                doc_type=doc_type,
                slug=slug,
                body=json.dumps(validated.model_dump()),
                meta=json.dumps(doc_meta),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                published=False,
                published_at=None,
            )
        ).run()

        rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()

        loop = asyncio.get_running_loop()
        loop.create_task(fire_event(cms, "document.created", doc_id, doc_type, slug))

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

        try:
            patch_data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        row = rows[0]
        doc_type = row["doc_type"]
        doc_model = cms._document_types.get(doc_type)

        # Merge body
        existing_body = row.get("body", "{}")
        if isinstance(existing_body, str):
            try:
                existing_body = json.loads(existing_body)
            except Exception:
                existing_body = {}

        new_body_data = patch_data.get("body", {})
        merged_body = {**existing_body, **new_body_data}

        # Validate merged body if we have a model
        if doc_model is not None:
            try:
                validated = doc_model.model_validate(merged_body)
                merged_body = validated.model_dump()
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

        update_kwargs: dict[Column | str, Any] = {
            CMSDocument.body: json.dumps(merged_body),
            CMSDocument.updated_at: datetime.now(UTC),
        }

        if "slug" in patch_data:
            update_kwargs[CMSDocument.slug] = patch_data["slug"]

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

        now = datetime.now(UTC)
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

        loop = asyncio.get_running_loop()
        loop.create_task(
            fire_event(
                cms,
                "document.published",
                doc_id,
                updated_row["doc_type"],
                updated_row.get("slug", ""),
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

    return [
        Route("/api/documents", endpoint=list_documents, methods=["GET"]),
        Route("/api/documents", endpoint=create_document, methods=["POST"]),
        Route("/api/documents/{id}", endpoint=get_document, methods=["GET"]),
        Route("/api/documents/{id}", endpoint=patch_document, methods=["PATCH"]),
        Route("/api/documents/{id}", endpoint=delete_document, methods=["DELETE"]),
        Route("/api/documents/{id}/publish", endpoint=publish_document, methods=["POST"]),
        Route("/api/documents/{id}/unpublish", endpoint=unpublish_document, methods=["POST"]),
    ]
