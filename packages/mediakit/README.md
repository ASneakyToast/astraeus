# mediakit

Media management for Starlette — S3-compatible storage, IIIF Image API 3.0, presigned upload flow, and an admin UI.

Part of the [Astraeus](https://github.com/ASneakyToast/astraeus) content stack.

## Install

```bash
pip install mediakit            # core only
pip install mediakit[admin]     # + admin UI (Jinja2 templates)
pip install mediakit[mcp]       # + MCP server for agent tool use
pip install mediakit[full]      # everything
```

## Quickstart

```python
from mediakit.adapters.starlette import create_media_mount

media = create_media_mount(
    bucket="my-bucket",
    endpoint_url="https://storage.googleapis.com",  # GCS, R2, or None for AWS S3
    catalog_path="./media.db",
    auth=lambda request: request.user.is_authenticated,
)

app = Starlette(routes=[Mount("/media", app=media)], lifespan=media.lifespan)
# Admin at: /media/admin
# IIIF at:  /media/iiif/{key}/full/800,/0/default.webp
```

## Status

Pre-release. Spec complete, implementation in progress.
