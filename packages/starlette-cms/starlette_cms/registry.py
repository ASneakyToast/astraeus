"""
Block registry — maps block type names to their Pydantic model classes.

Supports two registration patterns:
- @cms.block("name") — first-party, immediate registration into a CMS instance
- @block("name")     — standalone, deferred registration (for packages/libraries)
"""

from __future__ import annotations

from typing import Any, TypeVar

from starlette_cms.exceptions import BlockNotFound, BlockRegistrationError

T = TypeVar("T")


def block(name: str):
    """
    Standalone block decorator. Marks a class as a block definition without
    registering it anywhere. Registration is always explicit::

        @block("gallery")
        class GalleryBlock:
            heading: str = TextField(label="Gallery title")

        # Later, in application code:
        cms.register_block(GalleryBlock)
    """
    def decorator(cls: type[T]) -> type[T]:
        cls.__block_type__ = name  # type: ignore[attr-defined]
        return cls
    return decorator


class BlockRegistry:
    """
    Central registry mapping block type names to their class definitions.

    All registration must happen before cms.app is first accessed.
    """

    def __init__(self) -> None:
        self._blocks: dict[str, type] = {}

    def register_block(self, block_cls: type, *, override: bool = False) -> None:
        """Register a single block class."""
        name = getattr(block_cls, "__block_type__", None)
        if name is None:
            raise BlockRegistrationError(
                f"{block_cls.__name__} is not decorated with @block() or @cms.block()."
            )
        if name in self._blocks and not override:
            raise BlockRegistrationError(
                f'Block type "{name}" is already registered. '
                f"Use override=True to replace it explicitly."
            )
        self._blocks[name] = block_cls

    def register_blocks(self, block_classes: list[type], *, override: bool = False) -> None:
        """Register multiple block classes at once."""
        for cls in block_classes:
            self.register_block(cls, override=override)

    def get(self, name: str) -> type:
        """Return the block class for a given type name."""
        if name not in self._blocks:
            raise BlockNotFound(f'Block type "{name}" is not registered.')
        return self._blocks[name]

    def all(self) -> dict[str, type]:
        """Return all registered block types."""
        return dict(self._blocks)

    def names(self) -> list[str]:
        """Return all registered block type names."""
        return list(self._blocks.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._blocks
