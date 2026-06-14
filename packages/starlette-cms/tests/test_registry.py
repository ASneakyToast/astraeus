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


# ---------------------------------------------------------------------------
# Singleton flag
# ---------------------------------------------------------------------------


def test_singleton_flag_stored():
    """registry.is_singleton() returns True for singleton blocks."""
    registry = BlockRegistry()

    @block("storage_rates", singleton=True)
    class StorageRates:
        rate: float = TextField(required=True)

    registry.register_block(StorageRates)
    assert registry.is_singleton("storage_rates") is True


def test_non_singleton_flag_false():
    """registry.is_singleton() returns False for regular blocks."""
    registry = BlockRegistry()

    @block("jewelry_item")
    class JewelryItem:
        name: str = TextField(required=True)

    registry.register_block(JewelryItem)
    assert registry.is_singleton("jewelry_item") is False


def test_singleton_get_returns_model():
    """registry.get() still returns the Pydantic model class for singletons."""
    import pydantic

    registry = BlockRegistry()

    @block("config_block", singleton=True)
    class ConfigBlock:
        value: str = TextField(required=True)

    registry.register_block(ConfigBlock)
    model = registry.get("config_block")
    assert issubclass(model, pydantic.BaseModel)
    assert model.__block_type__ == "config_block"  # type: ignore[attr-defined]


def test_singleton_via_register_block_kwarg():
    """singleton=True can be passed directly to register_block()."""
    registry = BlockRegistry()

    @block("rates_block")
    class RatesBlock:
        rate: str = TextField(required=True)

    registry.register_block(RatesBlock, singleton=True)
    assert registry.is_singleton("rates_block") is True


def test_is_singleton_raises_for_unknown_block():
    """is_singleton() raises BlockNotFound for unregistered types."""
    registry = BlockRegistry()
    with pytest.raises(BlockNotFound):
        registry.is_singleton("nonexistent")
