"""Feedback API — auth, validation and triage round-trips through the CMS app."""

from __future__ import annotations

import pytest

from .conftest import auth_headers

pytestmark = pytest.mark.asyncio

_VALID = {"description": "It broke.", "kind": "bug", "title": "Editor crashes"}


async def test_every_route_requires_auth(feedback_app):
    client = feedback_app["client"]

    assert (await client.get("/cms/api/feedback")).status_code == 401
    assert (await client.post("/cms/api/feedback", json=_VALID)).status_code == 401
    assert (await client.get("/cms/api/feedback/abc")).status_code == 401
    assert (await client.patch("/cms/api/feedback/abc", json={})).status_code == 401


async def test_file_then_read_back(feedback_app):
    client = feedback_app["client"]

    created = await client.post("/cms/api/feedback", json=_VALID, headers=auth_headers())
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "new"

    fetched = await client.get(f"/cms/api/feedback/{body['id']}", headers=auth_headers())
    assert fetched.status_code == 200
    assert fetched.json() == body


async def test_create_rejects_unknown_kind(feedback_app):
    resp = await feedback_app["client"].post(
        "/cms/api/feedback", json={**_VALID, "kind": "rant"}, headers=auth_headers()
    )

    assert resp.status_code == 422


async def test_create_rejects_missing_description(feedback_app):
    payload = {k: v for k, v in _VALID.items() if k != "description"}

    resp = await feedback_app["client"].post(
        "/cms/api/feedback", json=payload, headers=auth_headers()
    )

    assert resp.status_code == 422


async def test_create_rejects_non_object_body(feedback_app):
    resp = await feedback_app["client"].post(
        "/cms/api/feedback", json=["nope"], headers=auth_headers()
    )

    assert resp.status_code == 400


async def test_cannot_set_status_when_filing(feedback_app):
    resp = await feedback_app["client"].post(
        "/cms/api/feedback", json={**_VALID, "status": "fixed"}, headers=auth_headers()
    )

    assert resp.status_code == 201
    assert resp.json()["status"] == "new"


async def test_patch_triages_but_not_reporter_words(feedback_app):
    client = feedback_app["client"]
    created = (await client.post("/cms/api/feedback", json=_VALID, headers=auth_headers())).json()

    resp = await client.patch(
        f"/cms/api/feedback/{created['id']}",
        json={"status": "triaged", "title": "Rewritten", "triage_notes": "Repro'd."},
        headers=auth_headers(),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "triaged"
    assert body["triage_notes"] == "Repro'd."
    assert body["title"] == "Editor crashes"


async def test_patch_unknown_report_is_404(feedback_app):
    resp = await feedback_app["client"].patch(
        "/cms/api/feedback/nope", json={"status": "fixed"}, headers=auth_headers()
    )

    assert resp.status_code == 404


async def test_list_filters_by_status_and_rejects_bad_value(feedback_app):
    client = feedback_app["client"]
    first = (await client.post("/cms/api/feedback", json=_VALID, headers=auth_headers())).json()
    await client.post("/cms/api/feedback", json=_VALID, headers=auth_headers())
    await client.patch(
        f"/cms/api/feedback/{first['id']}", json={"status": "fixed"}, headers=auth_headers()
    )

    fixed = await client.get("/cms/api/feedback?status=fixed", headers=auth_headers())
    assert fixed.json()["total"] == 1

    bad = await client.get("/cms/api/feedback?status=bogus", headers=auth_headers())
    assert bad.status_code == 400


async def test_reports_are_not_exposed_through_document_api(feedback_app):
    client = feedback_app["client"]
    await client.post("/cms/api/feedback", json=_VALID, headers=auth_headers())

    resp = await client.get("/cms/api/documents")

    assert resp.status_code == 200
    assert "Editor crashes" not in resp.text
