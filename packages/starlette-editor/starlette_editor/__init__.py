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

import logging as _logging

from starlette_editor.app import Editor

# Library contract: prevent "No handlers could be found" warnings in host apps
# that have not called setup_telemetry().  The host is responsible for adding
# real handlers; we only ensure the logger is known to the hierarchy.
_logging.getLogger("starlette_editor").addHandler(_logging.NullHandler())

__version__ = "0.2.0"

__all__ = ["Editor"]
