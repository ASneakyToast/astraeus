# ADR 007 — Content-addressed storage keys in Mediakit

**Status:** Accepted  
**Date:** 2026-05-28

---

## Context

Mediakit stores uploaded files in an S3-compatible object store. We need to decide on a key scheme — how files are named/addressed within the bucket.

Options:
1. Path-based: `uploads/{year}/{month}/{filename}` (common, simple)
2. UUID-based: `uploads/{uuid}/{filename}` (unique per upload)
3. Content-addressed: `originals/{sha256_prefix}/{filename}` (derived from file content)

---

## Decision

**Content-addressed keys:** `originals/{sha256_prefix}/{filename}`

The `sha256_prefix` is the first 16 hex characters of the SHA-256 hash of the file content, computed at upload time.

Derivatives are stored at: `derivatives/{sha256_prefix}/{iiif_params_hash}.{format}`

---

## Rationale

**No silent overwrites.** If you upload `photo.jpg` today and upload a different `photo.jpg` tomorrow, they get different keys because they have different content. Path-based and UUID-based schemes both allow silent overwrites if the same key is reused — content-addressed makes this impossible.

**Derivative cache invalidation is implicit.** When an asset is "replaced" (upload new version), the new file gets a new key. Derivatives at the old key become orphans — they still exist in the bucket but are no longer referenced. `mediakit gc` cleans them up. No explicit cache invalidation logic is needed anywhere.

**Deduplication for free.** If the same file is uploaded twice, it gets the same key. The second `confirm` call is a no-op (key already exists). No duplicate storage.

**The SHA prefix is not the full hash.** `sha256_prefix` is the first 16 hex chars (8 bytes). This provides sufficient collision resistance for a media library (collision probability is astronomically low at any realistic scale) while keeping keys reasonably short.

---

## Alternatives considered

**Path-based (`uploads/{year}/{month}/{filename}`)**  
Rejected. Silent overwrites are possible. No cache invalidation signal for derivatives. Chronological organization seems useful but is better served by the SQLite catalog's `created_at` field.

**UUID-based (`uploads/{uuid}/{filename}`)**  
Rejected. Unique per upload, but no content relationship. Uploading the same file twice creates two objects. No implicit derivative invalidation.

---

## Consequences

- There is **no "replace in place" operation.** Replacing a file is: upload new → get new key → update content references → optionally delete old key. This is intentional and correct — the old key remains valid until explicitly deleted, so existing references don't break immediately.
- `mediakit gc` is a required operational tool, not an optional nicety — orphaned derivatives will accumulate otherwise
- The catalog's `original_key` field stores the pre-processing key (raw upload); the `key` field stores the post-processing key (WebP-converted canonical version)
