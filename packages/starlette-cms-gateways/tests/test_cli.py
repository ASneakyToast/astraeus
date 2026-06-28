"""
Tests for the gateways CLI.

Tests discovery, list output, and the status command against a mocked CMS.
Entry point discovery is patched via unittest.mock so no real package
installation is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from starlette_cms_gateways.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ep(name: str, gateway_cls) -> MagicMock:
    """Build a fake importlib entry point."""
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = gateway_cls
    return ep


# ---------------------------------------------------------------------------
# Dummy gateway classes
# ---------------------------------------------------------------------------


class DummyGateway:
    service_name = "dummy"
    block_type = "dummy_item"
    auto_publish = True


class AnotherGateway:
    service_name = "another"
    block_type = "another_item"
    auto_publish = False


# ---------------------------------------------------------------------------
# gateways list
# ---------------------------------------------------------------------------


def test_list_no_gateways():
    runner = CliRunner()
    with patch(
        "starlette_cms_gateways.cli.entry_points",
        return_value=[],
    ):
        result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "No gateways found" in result.output


def test_list_shows_installed_gateways():
    eps = [
        _make_ep("dummy-gw", DummyGateway),
        _make_ep("another-gw", AnotherGateway),
    ]
    runner = CliRunner()
    with patch("starlette_cms_gateways.cli.entry_points", return_value=eps):
        result = runner.invoke(main, ["list"])
    assert result.exit_code == 0
    assert "dummy-gw" in result.output
    assert "another-gw" in result.output
    assert "dummy" in result.output  # service_name
    assert "another" in result.output


def test_list_shows_auto_publish_flag():
    eps = [_make_ep("a-gw", AnotherGateway)]
    runner = CliRunner()
    with patch("starlette_cms_gateways.cli.entry_points", return_value=eps):
        result = runner.invoke(main, ["list"])
    assert "auto_publish=False" in result.output


# ---------------------------------------------------------------------------
# gateways sync — missing URL
# ---------------------------------------------------------------------------


def test_sync_requires_cms_url():
    runner = CliRunner()
    with patch("starlette_cms_gateways.cli.entry_points", return_value=[]):
        result = runner.invoke(main, ["sync", "my-gw"])
    assert result.exit_code != 0
    assert "GATEWAYS_CMS_URL" in result.output or "cms-url" in result.output.lower()


def test_sync_unknown_gateway():
    runner = CliRunner()
    with patch("starlette_cms_gateways.cli.entry_points", return_value=[]):
        result = runner.invoke(
            main, ["sync", "unknown-gateway", "--cms-url", "http://localhost"]
        )
    assert result.exit_code != 0
    assert "Unknown gateway" in result.output


# ---------------------------------------------------------------------------
# Entry point discovery with a load error
# ---------------------------------------------------------------------------


def test_list_handles_load_error_gracefully(caplog):
    bad_ep = MagicMock()
    bad_ep.name = "broken-gw"
    bad_ep.load.side_effect = ImportError("missing dependency")

    good_ep = _make_ep("good-gw", DummyGateway)

    runner = CliRunner()
    import logging

    with caplog.at_level(logging.WARNING):
        with patch("starlette_cms_gateways.cli.entry_points", return_value=[bad_ep, good_ep]):
            result = runner.invoke(main, ["list"])

    # Should still exit cleanly and show the good gateway
    assert result.exit_code == 0
    assert "good-gw" in result.output
    # Warning now goes to structlog/logging, not click output
    assert any("broken-gw" in r.message or "broken-gw" in str(r.getMessage()) for r in caplog.records)
