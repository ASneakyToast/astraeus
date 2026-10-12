"""The MCP changeset tools, against a real in-process CMS.

A mock can only say what we told it the CMS does, and these tools exist to show
and move what the CMS has staged, so they run over an ASGI transport.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
from httpx import ASGITransport
from starlette_cms import CMS, TextField
from starlette_cms.mcp.server import build_mcp_server


@pytest_asyncio.fixture
async def mcp() -> AsyncGenerator[Any, None]:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cms = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="none",
            read_auth=False,
            default_changeset="Staging",
        )

        @cms.block("article")
        class ArticleBlock:
            title: str = TextField(required=True)

        async with cms.lifespan_context(None):
            yield build_mcp_server(
                base_url="http://testserver", transport=ASGITransport(app=cms.app)
            )
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


async def _call(mcp: Any, name: str, **kwargs: Any) -> Any:
    return await mcp._tool_manager._tools[name].fn(**kwargs)


async def _new_draft(mcp: Any, title: str) -> str:
    doc = await _call(mcp, "create_document", doc_type="article", body={"title": title})
    return doc["id"]


def _ids(changeset: dict[str, Any]) -> set[str]:
    return {d["id"] for d in changeset["documents"]}


async def test_tools_are_registered_with_the_right_annotations(mcp):
    tools = {t.name: t for t in await mcp.list_tools()}

    for name in ("list_changesets", "get_default_changeset", "get_changeset"):
        assert tools[name].annotations.readOnlyHint is True
    assert tools["publish_changeset"].annotations.openWorldHint is True
    assert "rebuilt" in tools["publish_changeset"].description
    for tool in tools.values():
        assert tool.inputSchema["additionalProperties"] is False, tool.name


async def test_no_default_changeset_until_a_draft_exists(mcp):
    assert await _call(mcp, "get_default_changeset") == {"changeset": None}


async def test_new_drafts_show_up_in_the_default_changeset(mcp):
    a = await _new_draft(mcp, "A")
    b = await _new_draft(mcp, "B")

    default = (await _call(mcp, "get_default_changeset"))["changeset"]

    assert default["title"] == "Staging"
    assert _ids(default) == {a, b}
    listed = (await _call(mcp, "list_changesets", status="open"))["changesets"]
    assert [cs["id"] for cs in listed] == [default["id"]]
    assert _ids(listed[0]) == {a, b}


async def test_list_without_documents_gives_only_the_count(mcp):
    await _new_draft(mcp, "A")

    listed = (await _call(mcp, "list_changesets", include_documents=False))["changesets"]

    assert listed[0]["document_count"] == 1
    assert "documents" not in listed[0]


async def test_moving_a_document_out_of_staging(mcp):
    keep = await _new_draft(mcp, "Ready")
    half = await _new_draft(mcp, "Half-written")
    staging = (await _call(mcp, "get_default_changeset"))["changeset"]

    parked = await _call(mcp, "create_changeset", title="Half-written")
    await _call(mcp, "add_document_to_changeset", changeset_id=parked["id"], doc_id=half)
    after = await _call(
        mcp, "remove_document_from_changeset", changeset_id=staging["id"], doc_id=half
    )

    assert _ids(after) == {keep}
    assert _ids(await _call(mcp, "get_changeset", changeset_id=parked["id"])) == {half}


async def test_adding_without_removing_leaves_it_in_both(mcp):
    doc = await _new_draft(mcp, "A")
    staging = (await _call(mcp, "get_default_changeset"))["changeset"]
    other = await _call(mcp, "create_changeset", title="Other")

    result = await _call(mcp, "add_document_to_changeset", changeset_id=other["id"], doc_id=doc)

    assert result["documents"][0]["also_in"] == [
        {"changeset_id": staging["id"], "title": "Staging"}
    ]


async def test_adding_twice_is_an_error_with_a_hint(mcp):
    doc = await _new_draft(mcp, "A")
    staging = (await _call(mcp, "get_default_changeset"))["changeset"]

    result = await _call(mcp, "add_document_to_changeset", changeset_id=staging["id"], doc_id=doc)

    assert "already in this changeset" in result["error"]
    assert "hint" in result


async def test_unknown_ids_are_errors_with_hints(mcp):
    doc = await _new_draft(mcp, "A")

    assert "error" in await _call(mcp, "get_changeset", changeset_id="nope")
    assert "error" in await _call(mcp, "publish_changeset", changeset_id="nope")
    assert "error" in await _call(mcp, "add_document_to_changeset", changeset_id="nope", doc_id=doc)
    assert "error" in await _call(
        mcp, "remove_document_from_changeset", changeset_id="nope", doc_id=doc
    )


async def test_publish_changeset_ships_its_documents_and_only_those(mcp):
    ready = await _new_draft(mcp, "Ready")
    half = await _new_draft(mcp, "Half-written")
    staging = (await _call(mcp, "get_default_changeset"))["changeset"]
    await _call(mcp, "remove_document_from_changeset", changeset_id=staging["id"], doc_id=half)

    result = await _call(mcp, "publish_changeset", changeset_id=staging["id"])

    assert result["status"] == "published"
    assert (await _call(mcp, "get_document", doc_id=ready))["published"] is True
    assert (await _call(mcp, "get_document", doc_id=half))["published"] is False
    # Publishing ended Staging: the next draft starts a fresh one.
    assert (await _call(mcp, "get_default_changeset")) == {"changeset": None}


async def test_publishing_a_published_changeset_is_an_error(mcp):
    await _new_draft(mcp, "A")
    staging = (await _call(mcp, "get_default_changeset"))["changeset"]
    await _call(mcp, "publish_changeset", changeset_id=staging["id"])

    result = await _call(mcp, "publish_changeset", changeset_id=staging["id"])

    assert "error" in result
    assert "hint" in result
