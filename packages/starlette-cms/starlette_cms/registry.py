"""
Block registry — maps block type names to their Pydantic model classes.

Supports two registration patterns:
- @cms.block("name") — first-party, immediate registration into a CMS instance
- @block("name")     — standalone, deferred registration (for packages/libraries)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeVar

from starlette_cms.exceptions import BlockNotFound, BlockRegistrationError
from starlette_cms.model_builder import build_block_model

T = TypeVar("T")


@dataclass
class BlockRegistration:
    """Metadata stored alongside each registered block model."""

    model: type
    singleton: bool = field(default=False)


def block(name: str, *, singleton: bool = False):
    """
    Standalone block decorator. Marks a class as a block definition without
    registering it anywhere. Registration is always explicit::

        @block("gallery")
        class GalleryBlock:
            heading: str = TextField(label="Gallery title")

        # Later, in application code:
        cms.register_block(GalleryBlock)

    Pass ``singleton=True`` to mark this block as a singleton type::

        @block("storage_rates", singleton=True)
        class StorageRates:
            rate: float = NumberField(default=0.005)
    """

    def decorator(cls: type[T]) -> type[T]:
        cls.__block_type__ = name  # type: ignore[attr-defined]
        cls.__singleton__ = singleton  # type: ignore[attr-defined]
        return cls

    return decorator


class BlockRegistry:
    """
    Central registry mapping block type names to their class definitions.

    All registration must happen before cms.app is first accessed.
    """

    def __init__(self) -> None:
        self._blocks: dict[str, BlockRegistration] = {}

    def register_block(
        self, block_cls: type, *, override: bool = False, singleton: bool = False
    ) -> None:
        """Register a single block class, converting it to a Pydantic model if needed."""
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
        # singleton kwarg to register_block() takes precedence; fall back to class attribute
        # set by the @block() decorator, then default False.
        cls_singleton = getattr(block_cls, "__singleton__", False)
        effective_singleton = singleton or cls_singleton

        # Convert to Pydantic model if not already one
        import pydantic

        if not (isinstance(block_cls, type) and issubclass(block_cls, pydantic.BaseModel)):
            block_cls = build_block_model(name, block_cls)
        self._blocks[name] = BlockRegistration(model=block_cls, singleton=effective_singleton)

    def register_blocks(self, block_classes: list[type], *, override: bool = False) -> None:
        """Register multiple block classes at once."""
        for cls in block_classes:
            self.register_block(cls, override=override)

    def get(self, name: str) -> type:
        """Return the block class for a given type name."""
        if name not in self._blocks:
            raise BlockNotFound(f'Block type "{name}" is not registered.')
        return self._blocks[name].model

    def is_singleton(self, name: str) -> bool:
        """Return True if the named block type is registered as a singleton."""
        if name not in self._blocks:
            raise BlockNotFound(f'Block type "{name}" is not registered.')
        return self._blocks[name].singleton

    def all(self) -> dict[str, type]:
        """Return all registered block types (as model classes)."""
        return {name: reg.model for name, reg in self._blocks.items()}

    def names(self) -> list[str]:
        """Return all registered block type names."""
        return list(self._blocks.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._blocks
