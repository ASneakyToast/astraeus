"""ProseMirror bridge — generates ProseMirror schema from the block registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette_cms.registry import BlockRegistry


# ---------------------------------------------------------------------------
# Standard ProseMirror nodes and marks (hard-coded PM primitives)
# ---------------------------------------------------------------------------

_BASE_NODES: dict[str, Any] = {
    "doc": {"content": "block+"},
    "paragraph": {
        "content": "inline*",
        "group": "block",
        "parseDOM": [{"tag": "p"}],
        "toDOM": ["p", 0],
    },
    "heading": {
        "content": "inline*",
        "group": "block",
        "attrs": {"level": {"default": 1}},
        "parseDOM": [
            {"tag": "h1", "attrs": {"level": 1}},
            {"tag": "h2", "attrs": {"level": 2}},
            {"tag": "h3", "attrs": {"level": 3}},
            {"tag": "h4", "attrs": {"level": 4}},
            {"tag": "h5", "attrs": {"level": 5}},
            {"tag": "h6", "attrs": {"level": 6}},
        ],
        "toDOM": [["h1", 0], ["h2", 0], ["h3", 0], ["h4", 0], ["h5", 0], ["h6", 0]],
    },
    "blockquote": {
        "content": "block+",
        "group": "block",
        "parseDOM": [{"tag": "blockquote"}],
        "toDOM": ["blockquote", 0],
    },
    "code_block": {
        "content": "text*",
        "group": "block",
        "code": True,
        "parseDOM": [{"tag": "pre", "preserveWhitespace": "full"}],
        "toDOM": ["pre", ["code", 0]],
    },
    "hard_break": {
        "inline": True,
        "group": "inline",
        "selectable": False,
        "parseDOM": [{"tag": "br"}],
        "toDOM": ["br"],
    },
    "text": {"group": "inline"},
}

_BASE_MARKS: dict[str, Any] = {
    "strong": {
        "parseDOM": [{"tag": "strong"}, {"tag": "b"}],
        "toDOM": ["strong", 0],
    },
    "em": {
        "parseDOM": [{"tag": "em"}, {"tag": "i"}],
        "toDOM": ["em", 0],
    },
    "code": {
        "parseDOM": [{"tag": "code"}],
        "toDOM": ["code", 0],
    },
    "link": {
        "attrs": {"href": {}, "title": {"default": None}},
        "inclusive": False,
        "parseDOM": [{"tag": "a[href]"}],
        "toDOM": ["a", 0],
    },
}


class ProseMirrorBridge:
    """
    Generates a ProseMirror-compatible schema definition from the block registry.
    Activated by starlette-editor at init time.
    """

    def __init__(self, registry: BlockRegistry) -> None:
        self.registry = registry

    def generate_schema(self) -> dict[str, Any]:
        """
        Return the ProseMirror schema definition for all registered blocks.

        The returned dict has three top-level keys:

        - ``nodes`` — standard ProseMirror node specs (doc, paragraph, heading, etc.)
        - ``marks`` — standard ProseMirror mark specs (strong, em, code, link)
        - ``blockTypes`` — editor metadata for each registered block::

            {
              "article": {
                "fields": {
                  "title":    {"field_type": "text",      "label": "Title", "required": True},
                  "body":     {"field_type": "rich_text", "label": "Body",  "required": False},
                  "category": {"field_type": "select",    "choices": [...], ...},
                }
              }
            }
        """
        block_types: dict[str, Any] = {}

        for name, model in self.registry.all().items():
            schema = model.model_json_schema()
            props = schema.get("properties", {})
            required_fields: set[str] = set(schema.get("required") or [])
            fields: dict[str, Any] = {}

            for field_name, prop in props.items():
                if field_name == "block_type":
                    # Injected discriminator — not a user-facing field
                    continue

                meta: dict[str, Any] = dict(prop.get("cms:field_meta") or {})

                # Derive a human-readable label if not already in meta
                if "label" not in meta:
                    meta["label"] = field_name.replace("_", " ").title()

                # Explicit required flag driven by the JSON Schema `required` array
                meta["required"] = field_name in required_fields

                # Infer field_type when not already set by the field class
                if "field_type" not in meta:
                    meta["field_type"] = _infer_field_type(prop, meta)

                fields[field_name] = meta

            block_types[name] = {"fields": fields}

        return {
            "nodes": _BASE_NODES,
            "marks": _BASE_MARKS,
            "blockTypes": block_types,
        }

    async def schema_endpoint(self, request: Request) -> JSONResponse:
        """Serves as the /api/editor-schema endpoint, registered via extension routes."""
        return JSONResponse(self.generate_schema())


def _infer_field_type(prop: dict[str, Any], meta: dict[str, Any]) -> str:
    """
    Heuristically derive a field_type string from JSON Schema prop and cms:field_meta.

    Explicit ``field_type`` keys (set by field classes like RichTextField, DocumentRef)
    take priority and are handled before this function is called.
    """
    # SelectField always has choices in meta
    if meta.get("choices"):
        return "select"

    # URL format marker from URLField
    if meta.get("format") == "url":
        return "url"

    # NumberField adds min_value / max_value / precision
    if any(k in meta for k in ("min_value", "max_value", "precision")):
        return "number"

    # JSONField may add a `schema` key; also catch raw object/array JSON types
    if "schema" in meta:
        return "json"

    json_type = prop.get("type")
    if json_type in ("object", "array"):
        return "json"

    # anyOf / oneOf may wrap nullable types — inspect the inner types
    any_of = prop.get("anyOf") or prop.get("oneOf") or []
    if any_of:
        inner_types = {s.get("type") for s in any_of if isinstance(s, dict)}
        if "object" in inner_types or "array" in inner_types:
            return "json"
        if json_type is None and not inner_types - {"null"}:
            return "json"

    if json_type in ("number", "integer"):
        return "number"

    if json_type == "boolean":
        return "boolean"

    # Default to plain text
    return "text"
