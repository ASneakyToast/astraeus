# CMS System Fields

Every document in starlette-cms has a fixed set of **system fields** — top-level
columns on the `CMSDocument` table that exist regardless of what you define in your
`@cms.document()` body schema.

## Reserved field names

| Field | Type | Description |
|---|---|---|
| `id` | `str` (UUID) | Immutable document identifier |
| `slug` | `str` | Human-readable URL key — set at create time, updatable |
| `doc_type` | `str` | The registered block type name (e.g. `"blog_post"`) |
| `published` | `bool` | Whether the document is publicly visible |
| `created_at` | `datetime` | Creation timestamp (UTC) |
| `updated_at` | `datetime` | Last-modified timestamp (UTC) |
| `meta` | `dict` | Arbitrary key/value store for CMS tooling (not content) |

These appear in every API response as top-level keys alongside `body`.

## The rule: never define system fields in a body schema

```python
# ❌ WRONG — slug is already a system field
@cms.document("blog_post")
class BlogPostDocument:
    slug: str = TextField(required=True)   # <-- don't do this
    title: str = TextField(required=True)

# ✅ CORRECT — only define content fields in the body
@cms.document("blog_post")
class BlogPostDocument:
    title: str = TextField(required=True)
```

If you define a system field in the body schema, three things go wrong:

1. **The editor shows it twice** — once as the CMS slug input, once as a body form field
2. **The API response is ambiguous** — `doc.slug` (system) and `doc.body.slug` (body) may diverge
3. **Astro content loaders break** — if the loader uses `d.slug` (correct) but the schema also
   expects `body.slug`, type errors or missing-field warnings appear at build time

## How slug works

`slug` is set when creating a document — either explicitly via the API or the editor's
slug input. It is stored on the `CMSDocument` row and indexed for fast lookup.

In the starlette-editor UI, slug is always rendered as a dedicated top-level field,
separate from the body form. It does not come from the body schema.

In Astro content loaders, use the top-level `d.slug` as the entry ID:

```ts
// ✅ correct
return docs.map((d) => ({
  id: d.slug,          // top-level system field
  ...d.body,
  _id: d.id,
}));

// ❌ wrong — body.slug may not exist or may diverge from the real slug
return docs.map((d) => ({
  id: d.body['slug'],  // don't do this
  ...d.body,
}));
```

## Runtime guard

`@cms.document()` will emit a `warnings.warn` if any body field name matches a
reserved system field. Treat this as an error — fix it before deploying.

## History

This was discovered during the initial joellithgow.com → Astraeus migration (June 2026).
`slug` was defined in all three document schemas (`blog_post`, `project_page`,
`experience_entry`) because the original Markdown frontmatter files had a `slug` field.
The seed script copied it faithfully into the body JSON, and the CMS schema was defined
to match. This worked until the editor was built, at which point the duplicate field
became visible. The fix was to remove `slug` from all three body schemas and update the
Astro loaders to read from `d.slug` instead of `d.body['slug']`.
