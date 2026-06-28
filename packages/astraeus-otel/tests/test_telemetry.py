"""Tests for astraeus_otel setup_telemetry() and TelemetryConfig."""

from __future__ import annotations

import os

import astraeus_otel.setup as _setup_module
import pytest
from astraeus_otel.config import TelemetryConfig
from astraeus_otel.setup import reset_for_tests, setup_telemetry


@pytest.fixture(autouse=True)
def reset_telemetry_state():
    """Reset the idempotency guard before and after every test."""
    reset_for_tests()
    yield
    reset_for_tests()


def test_telemetry_config_defaults():
    """TelemetryConfig() has sensible defaults without any env vars set."""
    # Unset env vars that might bleed in from the environment
    for var in ("OTEL_SERVICE_NAME", "ASTRAEUS_OTLP_ENDPOINT", "ASTRAEUS_LOG_LEVEL"):
        os.environ.pop(var, None)

    config = TelemetryConfig()

    assert isinstance(config.service_name, str)
    assert config.service_name  # non-empty
    assert config.otlp_endpoint is None or isinstance(config.otlp_endpoint, str)
    assert isinstance(config.enable_console, bool)
    assert config.structlog_renderer in ("auto", "console", "json")


def test_telemetry_config_reads_otel_env_vars():
    """TelemetryConfig() picks up OTEL_SERVICE_NAME from the environment."""
    os.environ["OTEL_SERVICE_NAME"] = "my-service"
    try:
        config = TelemetryConfig()
        assert config.service_name == "my-service"
    finally:
        del os.environ["OTEL_SERVICE_NAME"]


def test_setup_telemetry_with_explicit_config():
    """setup_telemetry() succeeds when given an explicit TelemetryConfig."""
    config = TelemetryConfig(service_name="test-svc", enable_console=False)
    # Should not raise
    setup_telemetry(config)
    assert _setup_module._configured is True


def test_setup_telemetry_is_idempotent():
    """Calling setup_telemetry() twice is a no-op on the second call."""
    config = TelemetryConfig(service_name="idempotent-test", enable_console=False)
    setup_telemetry(config)
    # Mark as configured — second call should return early without error
    assert _setup_module._configured is True
    setup_telemetry(config)  # must not raise or re-configure
    assert _setup_module._configured is True


def test_setup_telemetry_resets_for_tests():
    """reset_for_tests() clears the idempotency flag so setup_telemetry() re-runs."""
    config = TelemetryConfig(service_name="reset-test", enable_console=False)
    setup_telemetry(config)
    assert _setup_module._configured is True

    reset_for_tests()
    assert _setup_module._configured is False

    # Can now call setup_telemetry() again without it being a no-op
    setup_telemetry(config)
    assert _setup_module._configured is True
