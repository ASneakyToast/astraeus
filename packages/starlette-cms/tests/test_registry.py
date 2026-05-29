"""Tests for BlockRegistry."""

from __future__ import annotations

import pytest
from starlette_cms import TextField
from starlette_cms.exceptions import BlockNotFound, BlockRegistrationError
from starlette_cms.registry import BlockRegistry, block

# ---------------------------------------------------------------------------
# Basic registration
# ---------------------------------------------------------------------------


def test_register_and_get():
    registry = BlockRegistry()

    @block("hero")
    class HeroBlock:
        title: str = TextField(required=True)

    registry.register_block(HeroBlock)
    model = registry.get("hero")
    assert model.__block_type__ == "hero"  # type: ignore[attr-defined]


def test_register_converts_to_pydantic_model():
    """register_block() converts plain class to Pydantic model."""
    import pydantic

    registry = BlockRegistry()

    @block("card")
    class CardBlock:
        text: str = TextField(required=True)

    registry.register_block(CardBlock)
    model = registry.get("card")
    assert issubclass(model, pydantic.BaseModel)


def test_all_returns_registered_blocks():
    registry = BlockRegistry()

    @block("a")
    class A:
        title: str = TextField(required=True)

    @block("b")
    class B:
        body: str = TextField(required=True)

    registry.register_block(A)
    registry.register_block(B)
    assert set(registry.all().keys()) == {"a", "b"}


def test_names_returns_list():
    registry = BlockRegistry()

    @block("x")
    class X:
        title: str = TextField(required=True)

    registry.register_block(X)
    assert "x" in registry.names()


def test_contains():
    registry = BlockRegistry()

    @block("z")
    class Z:
        title: str = TextField(required=True)

    registry.register_block(Z)
    assert "z" in registry
    assert "missing" not in registry


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_duplicate_raises_registration_error():
    registry = BlockRegistry()

    @block("hero")
    class HeroBlock:
        title: str = TextField(required=True)

    registry.register_block(HeroBlock)
    with pytest.raises(BlockRegistrationError, match="already registered"):
        registry.register_block(HeroBlock)


def test_override_replaces():
    registry = BlockRegistry()

    @block("hero")
    class HeroBlockV1:
        title: str = TextField(required=True)

    @block("hero")
    class HeroBlockV2:
        headline: str = TextField(required=True)

    registry.register_block(HeroBlockV1)
    registry.register_block(HeroBlockV2, override=True)

    model = registry.get("hero")
    # V2 should have "headline" field
    assert "headline" in model.model_fields


def test_get_raises_block_not_found():
    registry = BlockRegistry()
    with pytest.raises(BlockNotFound, match="not registered"):
        registry.get("nonexistent")


def test_register_without_decorator_raises():
    """Classes without __block_type__ cannot be registered."""
    registry = BlockRegistry()

    class Bare:
        title: str = TextField(required=True)

    with pytest.raises(BlockRegistrationError, match="not decorated"):
        registry.register_block(Bare)


# ---------------------------------------------------------------------------
# register_blocks
# ---------------------------------------------------------------------------


def test_register_blocks_batch():
    registry = BlockRegistry()

    @block("aa")
    class AA:
        title: str = TextField(required=True)

    @block("bb")
    class BB:
        title: str = TextField(required=True)

    registry.register_blocks([AA, BB])
    assert "aa" in registry
    assert "bb" in registry
