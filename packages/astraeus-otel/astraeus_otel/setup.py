"""
setup_telemetry() — wire the OTEL SDK + structlog processor chain.

Call once at application startup, before the ASGI server starts accepting
requests.  Safe to call multiple times (idempotent guard via module-level flag).
"""

from __future__ import annotations

import logging
import sys

_configured = False


def reset_for_tests() -> None:
    """Reset the idempotency guard so ``setup_telemetry()`` can be called again.

    **Test use only.** Call in test teardown or a fixture to allow repeated
    ``setup_telemetry()`` calls within the same process.

    ::

        import astraeus_otel.setup as _setup

        def test_something():
            setup_telemetry(TelemetryConfig(enable_console=False))
            ...
            _setup.reset_for_tests()
    """
    global _configured
    _configured = False


def setup_telemetry(config=None) -> None:
    """
    Bootstrap OpenTelemetry SDK and structlog for all Astraeus packages.

    :param config: A :class:`~astraeus_otel.config.TelemetryConfig` instance.
        If ``None``, a default ``TelemetryConfig()`` is created, which reads
        from ``OTEL_*`` / ``ASTRAEUS_*`` environment variables.

    What this wires:

    1. OTEL ``TracerProvider`` with optional OTLP/gRPC export.
    2. OTEL ``LoggerProvider`` with optional OTLP/gRPC export.
    3. Starlette auto-instrumentation (HTTP spans per request).
    4. structlog processor chain → stdlib logging bridge.
    5. ``StreamHandler`` + ``OTLPLogHandler`` on the root stdlib logger.

    After this call, all ``structlog.get_logger()`` calls in the Astraeus
    packages emit structured log records that flow through OTEL's logs signal
    and to the console/JSON stream.
    """
    global _configured
    if _configured:
        return
    _configured = True

    from astraeus_otel.config import TelemetryConfig

    if config is None:
        config = TelemetryConfig()

    _setup_traces(config)
    _setup_logs(config)
    _setup_structlog(config)


def _setup_traces(config) -> None:
    """Initialise TracerProvider with optional OTLP export."""
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    resource = Resource.create({"service.name": config.service_name})
    provider = TracerProvider(resource=resource)

    if config.otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=config.otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    if config.enable_console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)

    # Starlette auto-instrumentation — wraps each request in a span
    try:
        from opentelemetry.instrumentation.starlette import StarletteInstrumentor

        StarletteInstrumentor().instrument()
    except ImportError:
        pass  # Starlette not installed in this env — safe to skip


def _setup_logs(config) -> None:
    """Initialise LoggerProvider with optional OTLP export, bridge to stdlib."""
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create({"service.name": config.service_name})
    log_provider = LoggerProvider(resource=resource)

    if config.otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

        exporter = OTLPLogExporter(endpoint=config.otlp_endpoint)
        log_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

    set_logger_provider(log_provider)

    # Bridge: stdlib logging → OTEL logs signal
    from opentelemetry.sdk._logs import LoggingHandler

    otel_handler = LoggingHandler(level=config.log_level, logger_provider=log_provider)

    root = logging.getLogger()
    root.setLevel(config.log_level)
    root.addHandler(otel_handler)


def _setup_structlog(config) -> None:
    """Configure structlog processor chain and add a StreamHandler to root logger."""
    import structlog

    # Determine renderer
    renderer = config.structlog_renderer
    if renderer == "auto":
        use_console = sys.stdout.isatty() or config.enable_console
    elif renderer == "console":
        use_console = True
    else:
        use_console = False

    if use_console:
        final_renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        final_renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            # Bridge to stdlib — structlog emits via logging.getLogger(name)
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(config.log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ProcessorFormatter renders structlog records that arrive via stdlib
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            final_renderer,
        ],
    )

    # Attach a StreamHandler so output actually goes somewhere even without OTLP
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(config.log_level)

    root = logging.getLogger()
    # Only add if no StreamHandler already present (idempotence for test suites)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        root.addHandler(handler)
