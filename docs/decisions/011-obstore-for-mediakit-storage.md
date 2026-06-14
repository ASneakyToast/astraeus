# ADR 011 — obstore as the storage client for Mediakit

**Status:** Accepted  
**Date:** 2026-06-13

---

## Context

Mediakit needs a Python client to interact with S3-compatible object stores (AWS S3, Google Cloud Storage,
Cloudflare R2). The client must support three operations:

1. **Presigned PUT URLs** — so browsers can upload directly to the bucket (no server proxying)
2. **Presigned GET URLs / public URLs** — so IIIF derivatives can be served via 302 redirect (no server proxying)
3. **Object existence checks, deletes, and bucket listing** — for catalog reconciliation and GC

The original scaffold committed to **boto3** (AWS's official Python SDK) as the storage client.

### Problem with boto3

boto3 is synchronous. In an asyncio application (Starlette), every boto3 call must either:
- Run in a thread executor: `await asyncio.to_thread(client.generate_presigned_url, ...)`
- Use `aioboto3`, an unofficial third-party async wrapper

The thread executor approach works but is boilerplate-heavy and introduces context switching overhead.
`aioboto3` is not AWS-maintained and has a history of lagging behind boto3 releases.

### Alternative considered: fsspec

fsspec provides a unified filesystem interface across backends. Rejected because:
- fsspec proxies data through the Python process — directly contradicts mediakit's no-proxying architecture
- fsspec has no concept of presigned URLs (they are not a filesystem primitive)
- boto3 would still be required underneath for presigned URL generation

---

## Decision

Use **obstore** (`pip install obstore`) as the storage client for all of mediakit's Phase 6+
storage operations.

The `S3CompatibleBackend` in `mediakit/storage/s3_compatible.py` will be implemented using obstore's
`S3Store` (covering AWS S3 and Cloudflare R2) and `GCSStore` (covering Google Cloud Storage).

Presigned URLs are generated via `obstore.sign_async(store, method, path, expires_in)`.

---

## Rationale

**Async-native.** obstore is built on the `object_store` Rust crate with first-class asyncio support.
No thread executors, no unofficial wrappers. `await obstore.sign_async(...)` is a real async call.

**Presigned URL support.** The `sign` / `sign_async` API supports PUT and GET signing across S3, GCS,
and Azure — exactly what the browser-direct upload and IIIF redirect flows need.

**S3-compatible endpoint support.** `S3Store` accepts an endpoint URL override, covering Cloudflare R2
and any other S3-compatible backend with one store class.

**High throughput.** Benchmarks show significantly better throughput than boto3/aioboto3 for multipart
uploads and parallel fetches — relevant for IIIF derivative generation where multiple derivatives may
be generated and uploaded concurrently.

**Maturity.** The underlying `object_store` Rust crate is production-grade (used in Apache DataFusion,
Delta Lake, Lance). The Python bindings (`obstore`) reached v0.10.1 as of June 2026, with active
maintenance and a stable API surface for the operations mediakit needs.

---

## Implementation notes

The `StorageBackend` protocol (defined in `mediakit/storage/backend.py`) is unchanged — it remains
the interface that the rest of mediakit codes against. `S3CompatibleBackend` is the concrete
implementation that uses obstore internally.

Store construction:

```python
import obstore.store as obs
from datetime import timedelta

# AWS S3
store = obs.S3Store.from_url(f"s3://{bucket}/", config={"AWS_REGION": region})

# Cloudflare R2 or any S3-compatible endpoint
store = obs.S3Store.from_url(
    f"s3://{bucket}/",
    config={
        "AWS_ENDPOINT": endpoint_url,
        "AWS_ACCESS_KEY_ID": access_key_id,
        "AWS_SECRET_ACCESS_KEY": secret_access_key,
    },
)

# GCS
store = obs.GCSStore.from_url(f"gs://{bucket}/")
```

Presigned URL generation:

```python
import obstore

# Browser upload URL (15 min default)
upload_url = await obstore.sign_async(store, "PUT", key, timedelta(seconds=expires_in))

# IIIF redirect URL
serve_url = await obstore.sign_async(store, "GET", key, timedelta(seconds=expires_in))
```

---

## Alternatives considered

**boto3 + asyncio.to_thread**  
Viable but verbose. Every storage call needs a thread executor wrapper. Chosen as the original
scaffold default due to familiarity, but no implementation was written so there's no migration cost.

**aioboto3**  
Async wrapper around boto3. Not AWS-maintained; has historically lagged boto3. Adds a dependency
without removing the boto3 dependency (aioboto3 wraps it). Rejected in favour of a clean native-async
implementation.

**s3fs / gcsfs**  
fsspec-based filesystem adapters. Same objection as fsspec itself — proxy-based, no presigned URLs.

---

## Consequences

- `boto3` is removed from `mediakit`'s core dependencies. It is no longer needed.
- `obstore` is added as a core dependency.
- The `S3CompatibleBackend` class name is retained (it still covers S3-compatible backends including R2).
  Internally it uses obstore, but callers only see the `StorageBackend` protocol.
- GCS is now a first-class backend (via `GCSStore`) rather than a "works because GCS speaks S3" footnote.
  The config distinguishes the two at construction time.
- If a future backend (Azure Blob) is needed, obstore's `AzureStore` is a natural addition — same API.
