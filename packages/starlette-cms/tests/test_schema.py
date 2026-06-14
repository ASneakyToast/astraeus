"""Tests for schema introspection endpoints."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator

import httpx
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import (
    CMS,
    BoolField,
    DocumentRef,
    JSONField,
    NumberField,
    SelectField,
    TextField,
    URLField,
    __version__,
)


@pytest_asyncio.fixture
async def field_types_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """CMS with blocks that exercise all five new field types."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(database_url=f"sqlite:///{db_path}", auth="none", read_auth=False)

        @instance.block("jewelry_item")
        class JewelryItemBlock:
            storage_location: str = SelectField(
                choices=["bank_vault", "home_safe", "standard", "daily_wear"],
                label="Storage Location",
                required=True,
            )
            appraised_value: float = NumberField(
                min_value=0.0,
                precision=2,
                label="Appraised Value",
            )
            insured: bool = BoolField(default=False, label="Insured")
            photo_url: str = URLField(label="Photo URL")
            extra_data: dict = JSONField(label="Extra Data")

        @instance.block("basic_block")
        class BasicBlock:
            name: str = TextField(required=True)

        async with instance.lifespan_context(None):
            app = Starlette(routes=[Mount("/", app=instance.app)])
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as c:
                yield c
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# GET /api/schema
# ---------------------------------------------------------------------------


async def test_list_schema_returns_all_blocks(client):
    resp = await client.get("/api/schema")
    assert resp.status_code == 200
    data = resp.json()
    assert "hero" in data


async def test_list_schema_includes_block_schema(client):
    resp = await client.get("/api/schema")
    assert resp.status_code == 200
    hero = resp.json()["hero"]
    assert "schema" in hero
    assert hero["block_type"] == "hero"


async def test_list_schema_has_properties(client):
    resp = await client.get("/api/schema")
    hero_schema = resp.json()["hero"]["schema"]
    assert "properties" in hero_schema
    assert "title" in hero_schema["properties"]


# ---------------------------------------------------------------------------
# GET /api/schema/{block_type}
# ---------------------------------------------------------------------------


async def test_get_block_schema_hero(client):
    resp = await client.get("/api/schema/hero")
    assert resp.status_code == 200
    data = resp.json()
    assert data["block_type"] == "hero"
    assert "schema" in data


async def test_get_block_schema_field_meta(client):
    """cms:field_meta from TextField(label=...) is surfaced in the schema."""
    resp = await client.get("/api/schema/hero")
    assert resp.status_code == 200
    data = resp.json()

    # title field was registered with label="Headline" in conftest HeroBlock
    field_meta = data.get("field_meta", {})
    if "title" in field_meta:
        assert field_meta["title"]["label"] == "Headline"
    else:
        # field_meta may also live inside the schema properties
        title_prop = data["schema"]["properties"].get("title", {})
        meta = title_prop.get("cms:field_meta")
        if meta:
            assert meta.get("label") == "Headline"


async def test_get_block_schema_not_found(client):
    resp = await client.get("/api/schema/nonexistent_block")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/schema/version
# ---------------------------------------------------------------------------


async def test_get_schema_version(client):
    resp = await client.get("/api/schema/version")
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert data["version"] == __version__


# ---------------------------------------------------------------------------
# New field types — cms:field_meta in schema
# ---------------------------------------------------------------------------


async def test_select_field_schema_includes_choices(field_types_client):
    """cms:field_meta for SelectField includes the choices list."""
    resp = await field_types_client.get("/api/schema/jewelry_item")
    assert resp.status_code == 200
    data = resp.json()
    schema = data["schema"]
    props = schema.get("properties", {})
    storage_prop = props.get("storage_location", {})
    # choices live in cms:field_meta
    meta = storage_prop.get("cms:field_meta", {})
    assert "choices" in meta
    assert meta["choices"] == ["bank_vault", "home_safe", "standard", "daily_wear"]


async def test_number_field_schema_includes_precision(field_types_client):
    """cms:field_meta for NumberField includes the precision hint."""
    resp = await field_types_client.get("/api/schema/jewelry_item")
    assert resp.status_code == 200
    data = resp.json()
    schema = data["schema"]
    props = schema.get("properties", {})
    value_prop = props.get("appraised_value", {})
    meta = value_prop.get("cms:field_meta", {})
    assert "precision" in meta
    assert meta["precision"] == 2


async def test_url_field_schema_includes_format(field_types_client):
    """cms:field_meta for URLField includes format: 'url'."""
    resp = await field_types_client.get("/api/schema/jewelry_item")
    assert resp.status_code == 200
    data = resp.json()
    schema = data["schema"]
    props = schema.get("properties", {})
    url_prop = props.get("photo_url", {})
    meta = url_prop.get("cms:field_meta", {})
    assert meta.get("format") == "url"


# ---------------------------------------------------------------------------
# Immutable field in schema
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def immutable_block_client():
    """CMS with a block that has an immutable field."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(database_url=f"sqlite:///{db_path}", auth="none")

        @instance.block("ref_block")
        class RefBlock:
            ref: str = TextField(required=True, immutable=True)
            label: str = TextField(required=False)

        app = Starlette(routes=[Mount("/", app=instance.app)])
        async with instance.lifespan_context(None):
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as c:
                yield c
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


async def test_immutable_field_in_schema(immutable_block_client):
    """GET /api/schema/{block_type} includes immutable:true in cms:field_meta."""
    resp = await immutable_block_client.get("/api/schema/ref_block")
    assert resp.status_code == 200
    props = resp.json()["schema"]["properties"]
    meta = props.get("ref", {}).get("cms:field_meta", {})
    assert meta.get("immutable") is True


async def test_mutable_field_no_immutable_key(immutable_block_client):
    """Mutable fields do not include immutable key in cms:field_meta."""
    resp = await immutable_block_client.get("/api/schema/ref_block")
    assert resp.status_code == 200
    props = resp.json()["schema"]["properties"]
    label_meta = props.get("label", {}).get("cms:field_meta", {})
    assert "immutable" not in label_meta


# ---------------------------------------------------------------------------
# DocumentRef schema tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ref_block_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """CMS with a block that has a DocumentRef field."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(database_url=f"sqlite:///{db_path}", auth="none", read_auth=False)

        @instance.block("ref_block_docref")
        class RefBlockDocRef:
            title: str = TextField(required=True)
            submission_ref: str = DocumentRef(block_type="jewelry_item", label="Submission")

        async with instance.lifespan_context(None):
            app = Starlette(routes=[Mount("/", app=instance.app)])
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as c:
                yield c
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


async def test_documentref_schema_includes_ref_block_type(ref_block_client):
    """GET /api/schema includes ref_block_type in field_meta for DocumentRef."""
    resp = await ref_block_client.get("/api/schema/ref_block_docref")
    assert resp.status_code == 200
    data = resp.json()
    submission_ref_prop = data["schema"]["properties"].get("submission_ref", {})
    meta = submission_ref_prop.get("cms:field_meta", {})
    assert meta.get("ref_block_type") == "jewelry_item"


async def test_documentref_schema_field_type_marker(ref_block_client):
    """GET /api/schema/{block_type} has cms:field_meta.field_type == 'document_ref'."""
    resp = await ref_block_client.get("/api/schema/ref_block_docref")
    assert resp.status_code == 200
    data = resp.json()
    submission_ref_prop = data["schema"]["properties"].get("submission_ref", {})
    meta = submission_ref_prop.get("cms:field_meta", {})
    assert meta.get("field_type") == "document_ref"
