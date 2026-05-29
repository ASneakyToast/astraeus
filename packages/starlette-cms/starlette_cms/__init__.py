"""
starlette-cms — Headless CMS for Starlette.

A mountable Starlette sub-application providing a block registry,
document store, content API, schema introspection, and webhook system.

Quickstart::

    from starlette_cms import CMS, TextField, RichTextField, ImageField, ListField

    cms = CMS(database_url="sqlite:///content.db", auth="apikey", api_key="secret")

    @cms.block("hero")
    class HeroBlock:
        title: str = TextField(required=True, label="Headline")
        body: dict = RichTextField()

    @cms.document("page")
    class PageDocument:
        title: str = TextField(required=True)
        slug: str = TextField(required=True)
        body: list = ListField(blocks=[HeroBlock])

    # Mount in your Starlette app:
    # app.mount("/cms", app=cms.app)
"""

from starlette_cms.app import CMS
from starlette_cms.registry import block
from starlette_cms.fields import (
    TextField,
    RichTextField,
    ImageField,
    ListField,
    BlockField,
)
from starlette_cms.exceptions import (
    CMSSchemaMismatch,
    BlockNotFound,
    BlockRegistrationError,
)

__version__ = "0.4.0"

__all__ = [
    "CMS",
    "block",
    "TextField",
    "RichTextField",
    "ImageField",
    "ListField",
    "BlockField",
    "CMSSchemaMismatch",
    "BlockNotFound",
    "BlockRegistrationError",
]
