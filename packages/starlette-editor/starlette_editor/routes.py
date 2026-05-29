"""Editor routes — /shell and /static/*"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.routing import Route, Mount

if TYPE_CHECKING:
    from starlette_editor.app import Editor


def make_editor_routes(editor: "Editor") -> list:
    # TODO: implement /shell and static file serving
    return []
