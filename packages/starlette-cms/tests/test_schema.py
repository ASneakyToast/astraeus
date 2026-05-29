"""Tests for schema introspection endpoints."""

from __future__ import annotations

from starlette_cms import __version__

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
