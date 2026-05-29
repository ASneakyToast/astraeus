"""
starlette-editor — Visual editing UI for starlette-cms.

A mountable Starlette sub-application providing a ProseMirror-based
editing interface, auto-generated from the starlette-cms block schema.

Quickstart::

    from starlette_cms import CMS
    from starlette_editor import Editor

    cms = CMS(database_url="sqlite:///content.db", auth="apikey", api_key="secret")
    editor = Editor(cms=cms)  # registers /api/editor-schema on cms before cms.app is built

    app = Starlette(
        routes=[Mount("/cms", app=cms.app), Mount("/editor", app=editor.app)],
        lifespan=cms.lifespan,
    )
"""

from starlette_editor.app import Editor

__version__ = "0.2.0"

__all__ = ["Editor"]
