"""
TelemetryConfig — Pydantic BaseSettings model for astraeus-otel.

Reads OTEL_* standard env vars first, then ASTRAEUS_* vars for anything OTEL
doesn't specify.  Pass an instance to ``setup_telemetry()`` or call
``setup_telemetry()`` with no arguments to read from the environment.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelemetryConfig(BaseSettings):
    """
    Configuration for the Astraeus OTEL bootstrap.

    All fields can be set via environment variables.  Standard OTEL env vars
    take precedence where they exist; Astraeus-specific vars cover the gaps.

    :param service_name: OTEL service name (``OTEL_SERVICE_NAME`` or
        ``ASTRAEUS_SERVICE_NAME``).
    :param otlp_endpoint: OTLP/gRPC exporter endpoint.  ``None`` disables
        OTLP export (``OTEL_EXPORTER_OTLP_ENDPOINT`` or
        ``ASTRAEUS_OTLP_ENDPOINT``).
    :param log_level: Stdlib log level integer applied to the root logger
        (``OTEL_LOG_LEVEL`` accepts ``DEBUG``/``INFO``/etc. as strings).
    :param enable_console: Force console (human-readable) output even when
        stdout is not a TTY.  Useful in Docker when you want pretty logs
        (``ASTRAEUS_ENABLE_CONSOLE``).
    :param structlog_renderer: ``"auto"`` (TTY-detect), ``"console"``, or
        ``"json"`` (``ASTRAEUS_STRUCTLOG_RENDERER``).
    """

    model_config = SettingsConfigDict(
        # ASTRAEUS_* prefix for Astraeus-specific fields; OTEL_* vars are
        # read via field_validators / default_factory to respect the standard.
        env_prefix="ASTRAEUS_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Identity ---
    service_name: str = Field(
        default_factory=lambda: os.environ.get("OTEL_SERVICE_NAME", "astraeus"),
        description="OTEL service name. Reads OTEL_SERVICE_NAME if ASTRAEUS_SERVICE_NAME is unset.",
    )

    # --- Export ---
    otlp_endpoint: str | None = Field(
        default_factory=lambda: os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
        description="OTLP/gRPC endpoint. None = no OTLP export.",
    )

    # --- Logging ---
    log_level: int = Field(
        default_factory=lambda: _parse_log_level(
            os.environ.get("OTEL_LOG_LEVEL", "INFO")
        ),
        description="Root stdlib log level. Accepts int or level-name string.",
    )

    # --- Dev ergonomics ---
    enable_console: bool = Field(
        default=False,
        description="Force ConsoleRenderer even when stdout is not a TTY.",
    )
    structlog_renderer: Literal["auto", "console", "json"] = Field(
        default="auto",
        description=(
            "'auto' = ConsoleRenderer on TTY, JSONRenderer otherwise. "
            "'console' / 'json' force a specific renderer."
        ),
    )


def _parse_log_level(value: str) -> int:
    """Parse a log level name or integer string into a logging level integer."""
    try:
        return int(value)
    except ValueError:
        level = getattr(logging, value.upper(), None)
        if isinstance(level, int):
            return level
        return logging.INFO
