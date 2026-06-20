"""
astraeus-otel — OpenTelemetry SDK bootstrap for the Astraeus package suite.

One-call setup that wires traces, structured logs, and OTEL export across all
Astraeus packages. Without this package, all OTEL API calls in the library
packages are no-ops.

Quickstart::

    from astraeus_otel import setup_telemetry, TelemetryConfig

    # Explicit config
    setup_telemetry(TelemetryConfig(service_name="my-service"))

    # Or read from OTEL_* / ASTRAEUS_* env vars
    setup_telemetry()
"""

from astraeus_otel.config import TelemetryConfig
from astraeus_otel.setup import setup_telemetry

__version__ = "0.1.0"

__all__ = ["setup_telemetry", "TelemetryConfig"]
