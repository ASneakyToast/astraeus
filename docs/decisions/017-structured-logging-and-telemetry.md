# ADR 017 — Structured logging and OpenTelemetry

**Status:** Accepted
**Date:** 2026-06-19

---

## Context

Astraeus packages currently have no coherent observability story. A single `logging.getLogger(__name__)`
call exists in `starlette_cms/api/webhooks.py`; no handler is installed anywhere; every other error path
either returns a JSON body to the HTTP caller or is silently swallowed in a bare `except Exception: pass`.
Twelve such silent swallows exist in `starlette_cms/api/documents.py` alone, covering JSON parse failures,
body coercion errors, and DB query errors. `mediakit/api/upload.py` silently drops processing-pipeline
failures. `starlette_cms_gateways/client.py` has a comment reading "log but don't raise" that does not
actually log.

As the package suite grows toward production use on joellithgow.com and client projects, this creates a
class of bug that is impossible to diagnose: the system misbehaves, no log line is emitted, the operator
has nothing to act on.

At the same time, Astraeus packages are reusable libraries installable from PyPI. The canonical Python
library rule is: libraries emit to a named logger and never configure handlers — configuration is the
host application's responsibility. Violating this rule forces handler configuration on every downstream
consumer, which breaks projects that have already configured their own logging stack.

These two constraints create a tension that requires a deliberate design decision.

---

## Decision

### Layer 1 — Library packages (`starlette-cms`, `mediakit`, `starlette-cms-gateways`, `starlette-editor`)

Each library package takes two direct dependencies:

- **`structlog`** — structured key-value log context, async-safe bound loggers, pluggable processor chain
- **`opentelemetry-api`** — trace/span/metric/log interfaces (~30 KB, pure Python, all calls are no-ops
  when no SDK is configured downstream)

Each package `__init__.py` installs a `logging.NullHandler()` on its root stdlib logger, satisfying the
library contract:

```python
# starlette_cms/__init__.py
import logging
logging.getLogger("starlette_cms").addHandler(logging.NullHandler())
```

Each module that emits logs or creates spans:

```python
import structlog
from opentelemetry import trace

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)
```

structlog is configured to fall back to the stdlib logging tree — its output flows to whatever handler
the host application has installed, which may include an `opentelemetry.sdk.logs.LoggingHandler`. No
processor chain or renderer is configured by the library packages themselves.

All bare `except Exception: pass` blocks are replaced with `logger.warning(...)` or
`logger.exception(...)` calls with structured key-value context. Critical paths (DB operations,
upload pipeline, gateway sync) additionally create OTEL spans so failures appear in traces.

### Layer 2 — SDK bootstrap package (`astraeus-otel`)

A new package `packages/astraeus-otel/` provides the SDK-side wiring. It depends on:

- `opentelemetry-sdk`
- `opentelemetry-exporter-otlp-proto-grpc` (OTLP/gRPC exporter)
- `opentelemetry-instrumentation-starlette` (auto-instrument HTTP spans)
- `structlog`

It exposes a single public entry point:

```python
from astraeus_otel import setup_telemetry, TelemetryConfig

# Option 1 — explicit config
setup_telemetry(TelemetryConfig(service_name="joellithgow-com"))

# Option 2 — reads from environment (OTEL_* vars + ASTRAEUS_* vars)
setup_telemetry()
```

`TelemetryConfig` is a Pydantic `BaseSettings` model. It reads standard OTEL environment variables
where they exist (`OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_LOG_LEVEL`,
`OTEL_TRACES_SAMPLER`, etc.) and adds Astraeus-specific fields where OTEL has no standard:

```python
class TelemetryConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASTRAEUS_")

    # Reads OTEL_SERVICE_NAME if not provided
    service_name: str = Field(default_factory=lambda: os.environ.get("OTEL_SERVICE_NAME", "astraeus"))

    # Reads OTEL_EXPORTER_OTLP_ENDPOINT if not provided
    otlp_endpoint: str | None = Field(
        default_factory=lambda: os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    )

    # Astraeus-specific: pretty ConsoleRenderer when True (for local dev)
    enable_console: bool = False

    # Astraeus-specific: structlog renderer override
    structlog_renderer: Literal["auto", "console", "json"] = "auto"
    # "auto" = ConsoleRenderer on TTY, JSONRenderer otherwise

    log_level: int = logging.INFO
```

`setup_telemetry()` with no arguments calls `TelemetryConfig()`, which reads from the environment.
This means a host app in a OTEL-aware deployment platform (Honeycomb, Datadog, Grafana Cloud) needs
only set the standard `OTEL_*` environment variables — no Astraeus-specific config required.

`setup_telemetry()` wires:
1. OTEL `TracerProvider` + `LoggerProvider` backed by the SDK, with OTLP export if `otlp_endpoint` is set
2. `opentelemetry-instrumentation-starlette` auto-instrumentation
3. structlog processor chain: `[add_log_level, add_timestamp, structlog→stdlib bridge, ConsoleRenderer|JSONRenderer]`
4. A `logging.StreamHandler` + `opentelemetry.sdk.logs.LoggingHandler` on the root stdlib logger at
   `log_level`, so all structlog output flows to both the console/JSON stream and the OTEL logs signal

### Layer 3 — Gateways CLI

The gateways CLI is an application, not a library. It calls `setup_telemetry()` at startup (using
`TelemetryConfig` read from env/flags) rather than relying on the host app. `click.echo` is retained
for UX-level output (final summaries, human-readable results). All operational log calls (per-item
sync errors, HTTP failures, unexpected exceptions) are replaced with `logger.warning/error` with
structured fields. The CLI gains `--verbose` / `--quiet` flags that set the effective log level.

---

## Rationale

**`opentelemetry-api` in libraries, `opentelemetry-sdk` in `astraeus-otel`.** This is the canonical
OTEL pattern — every official OTEL instrumentation library uses the API-only tier so they are no-ops
when the SDK is absent. Baking the SDK into `starlette-cms` would force SDK initialisation on every
consumer, including those using a different OTEL setup or none at all.

**`astraeus-otel` in the same monorepo as the library packages.** The SDK bootstrap must stay in
lockstep with the instrumentation hooks in the library packages. A separate repo creates version
skew risk — `astraeus-otel` referencing a span attribute added in `starlette-cms` 1.3 while a
consumer is on 1.2. One lockfile in the monorepo prevents this. The package still publishes to
PyPI independently and is independently installable; the monorepo is a development convenience.

**`TelemetryConfig` is `BaseSettings`, not kwargs.** Every other configuration model in Astraeus is
Pydantic. Consistency matters — operators already know the env-var-to-field mapping convention. A
`BaseSettings` model also makes `setup_telemetry()` testable: pass a config object with known values,
no env-var mocking required.

**OTEL env vars are respected where they exist.** `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`,
`OTEL_TRACES_SAMPLER`, etc. are a well-documented, platform-supported standard. Inventing
Astraeus-specific env vars for things OTEL already specifies would be wrong. `TelemetryConfig` reads
the OTEL standard vars first; Astraeus-specific vars (`ASTRAEUS_ENABLE_CONSOLE`, etc.) cover only
the gaps.

**structlog for ergonomics, OTEL for transport.** structlog's bound logger (`logger.bind(doc_id=...,
user=...)`) is async-safe and survives across `await` points without thread-local contamination.
OTEL's Python API has no equivalent for structured log context. structlog emits to stdlib logging;
stdlib logging bridges to OTEL's `LoggingHandler`. The two layers compose cleanly.

**Replace all silent swallows.** A bare `except Exception: pass` is not a performance optimisation —
it is a suppressed signal. Every such block is replaced with a structured log call at the appropriate
level (`WARNING` for expected degraded-mode fallbacks, `ERROR`/`exception()` for unexpected failures)
so that at minimum the error is visible in the stdlib root logger even without `astraeus-otel`.

---

## Alternatives considered

**structlog only, no OTEL.**
Rejected. structlog has no native trace/span primitive. OTEL's trace signal (parent/child span
relationships, service graphs, latency histograms) is qualitatively different from structured logs —
you cannot reconstruct a distributed trace from log lines alone. For a suite intended to serve
production workloads, traces are not optional.

**OTEL only, no structlog.**
Rejected. OTEL's Python logging API is verbose and has no async-safe bound-context primitive equivalent
to `structlog.get_logger(__name__).bind(...)`. Using raw `logging.getLogger` calls with `extra={...}`
dicts for every structured field is error-prone and hard to read. structlog is the ergonomics layer;
OTEL is the transport layer. They do not overlap.

**`opentelemetry-sdk` in the library packages directly.**
Rejected. Forces SDK initialisation on every consumer. Breaks projects that have already initialised
their own OTEL provider. Violates the OTEL project's explicit guidance for instrumentation libraries.

**`astraeus-otel` in a separate repository.**
Rejected. Creates version skew risk between the instrumentation hooks in library packages and the SDK
wiring in the bootstrap package. Monorepo co-development with a single lockfile is the correct tool.

**Keep `click.echo(err=True)` for all CLI output.**
Rejected for operational paths. `click.echo` is not filterable by level, not structured, not
capturable by a log handler, and not bridgeable to OTEL. It is correct for UX-level output (progress
indicators, human-readable summaries) and is retained for that purpose.

---

## Consequences

**Positive:**
- All error paths produce observable output; silent swallows are eliminated
- Host apps (joellithgow.com, VPP services) call `setup_telemetry()` once and get traces + structured
  logs across all Astraeus packages with no per-package wiring
- Standard OTEL env vars work out of the box — deployments on OTEL-aware platforms need no
  Astraeus-specific configuration
- `TelemetryConfig` is testable without env-var mocking
- Structlog's TTY-aware renderer gives a good local dev experience with no extra config

**Negative / tradeoffs:**
- `opentelemetry-api` and `structlog` become direct dependencies of every library package — two new
  transitive installs for consumers who don't use `astraeus-otel`
- `opentelemetry-api` no-ops are very cheap but not free — span/attribute calls have ~1–5 µs overhead
  on hot paths without an SDK configured
- Adding `astraeus-otel` to the monorepo increases `uv sync` scope slightly

**Neutral / deferred:**
- Metrics (counters, histograms) are in scope for OTEL but not the initial implementation; the tracer
  and logger setup in `astraeus-otel` will be extended to include a `MeterProvider` in a follow-on
- Per-request `request_id` propagation via structlog `bind_contextvars` + OTEL baggage is deferred to
  the request-logging middleware work item that follows this ADR
- `astraeus-otel` exporters beyond OTLP (Jaeger, Zipkin, Prometheus) are not included; consumers who
  need them can configure the SDK directly after calling `setup_telemetry()` and registering additional
  providers
