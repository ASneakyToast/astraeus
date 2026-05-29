"""
Astraeus demo — minimal full-stack integration.

Shows starlette-cms, starlette-editor, and mediakit working together.
Run with: uvicorn app:app --reload
"""

from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.routing import Mount

from starlette_cms import CMS, TextField, RichTextField, ImageField, ListField
from starlette_editor import Editor
from mediakit.adapters.starlette import create_media_mount

# --- CMS setup -----------------------------------------------------------

cms = CMS(
    database_url="sqlite:///demo.db",
    auth="apikey",
    api_key="dev-secret",
)


@cms.block("hero")
class HeroBlock:
    title: str = TextField(required=True, label="Headline")
    subtitle: str = TextField(label="Supporting text")
    image: str = ImageField(label="Hero image")


@cms.block("rich_text")
class RichTextBlock:
    body: dict = RichTextField(required=True, label="Content")


@cms.document("page")
class PageDocument:
    title: str = TextField(required=True)
    slug: str = TextField(required=True)
    body: list = ListField(blocks=[HeroBlock, RichTextBlock])


# --- Media setup ---------------------------------------------------------

media = create_media_mount(
    bucket="demo-bucket",
    endpoint_url="https://storage.googleapis.com",  # replace with your bucket
    catalog_path="./demo_media.db",
    auth="none",  # open for demo purposes
)

# --- Editor setup --------------------------------------------------------
# Editor extends cms here — registers /api/editor-schema before cms.app is built

editor = Editor(cms=cms, media_base="/media")


# --- Lifespan ------------------------------------------------------------

@asynccontextmanager
async def lifespan(app):
    async with cms.lifespan_context(app):
        async with media.lifespan_context(app):
            yield


# --- App -----------------------------------------------------------------

app = Starlette(
    routes=[
        Mount("/cms", app=cms.app),
        Mount("/media", app=media),
        Mount("/editor", app=editor.app),
    ],
    lifespan=lifespan,
)

# StandardEditor at: http://localhost:8000/editor/shell
# CMS API at:        http://localhost:8000/cms/api/documents
# Media API at:      http://localhost:8000/media/assets
