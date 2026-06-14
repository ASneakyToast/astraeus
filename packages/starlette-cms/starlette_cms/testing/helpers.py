"""
Testing helpers for starlette-cms block and registry authors.

Usage::

    from starlette_cms.testing import BlockTestCase, RegistryTestCase, validate_block

    class TestJewelryItem(BlockTestCase):
        block_cls = JewelryItem
        valid_data = {
            "declared_value": 8000.0,
            "storage_location": "home_safe",
            "item_description": "1ct diamond ring",
        }
"""

from __future__ import annotations

import unittest
from typing import Any

import pydantic


def validate_block(block_cls: type, data: dict[str, Any]) -> pydantic.BaseModel:
    """
    Validate ``data`` against ``block_cls``, returning the model instance on
    success or raising ``pydantic.ValidationError`` on failure.

    Builds the Pydantic model from the class if not already built.

    Example::

        model = validate_block(
            JewelryItem, {"declared_value": 8000, "storage_location": "home_safe"}
        )
        assert model.declared_value == 8000.0
    """
    from starlette_cms.model_builder import build_block_model

    if isinstance(block_cls, type) and issubclass(block_cls, pydantic.BaseModel):
        model_cls = block_cls
    else:
        name = getattr(block_cls, "__block_type__", block_cls.__name__.lower())
        model_cls = build_block_model(name, block_cls)

    return model_cls.model_validate(data)


class BlockTestCase(unittest.TestCase):
    """
    Base class for block definition tests.

    Subclasses must set ``block_cls``. Optionally set ``valid_data`` to pre-load
    a known-valid payload.

    Provides assertion helpers that reduce boilerplate::

        class TestJewelryItem(BlockTestCase):
            block_cls = JewelryItem
            valid_data = {
                "declared_value": 8000.0,
                "storage_location": "home_safe",
                "item_description": "1ct diamond ring",
            }
    """

    block_cls: type
    valid_data: dict[str, Any] = {}

    def setUp(self) -> None:
        from starlette_cms.model_builder import build_block_model

        if isinstance(self.block_cls, type) and issubclass(self.block_cls, pydantic.BaseModel):
            self._model = self.block_cls
        else:
            name = getattr(self.block_cls, "__block_type__", self.block_cls.__name__.lower())
            self._model = build_block_model(name, self.block_cls)

    def assert_valid(self, data: dict[str, Any]) -> pydantic.BaseModel:
        """Assert that data validates successfully. Returns the model instance."""
        return self._model.model_validate(data)

    def assert_invalid(self, data: dict[str, Any], *, field: str | None = None) -> None:
        """Assert that data fails validation. Optionally assert the error is on a specific field."""
        with self.assertRaises(pydantic.ValidationError) as ctx:
            self._model.model_validate(data)
        if field is not None:
            error_fields = [e["loc"][0] for e in ctx.exception.errors()]
            self.assertIn(field, error_fields, f"Expected validation error on field {field!r}")

    def assert_fields(self, *field_names: str) -> None:
        """Assert that the block model has all named fields."""
        model_fields = set(self._model.model_fields.keys())
        for name in field_names:
            self.assertIn(name, model_fields, f"Expected field {name!r} on {self._model.__name__}")

    def assert_field_label(self, field_name: str, expected_label: str) -> None:
        """Assert that a field's cms:field_meta label matches expected_label."""
        schema = self._model.model_json_schema()
        props = schema.get("properties", {})
        field_schema = props.get(field_name, {})
        meta = field_schema.get("cms:field_meta", {})
        actual = meta.get("label")
        self.assertEqual(
            actual,
            expected_label,
            f"Field {field_name!r}: expected label {expected_label!r}, got {actual!r}",
        )

    def assert_field_required(self, field_name: str) -> None:
        """Assert that a field is required (not optional)."""
        schema = self._model.model_json_schema()
        required = schema.get("required", [])
        self.assertIn(field_name, required, f"Expected {field_name!r} to be required")

    def assert_field_optional(self, field_name: str) -> None:
        """Assert that a field is optional."""
        schema = self._model.model_json_schema()
        required = schema.get("required", [])
        self.assertNotIn(field_name, required, f"Expected {field_name!r} to be optional")

    def assert_roundtrip(self, data: dict[str, Any]) -> None:
        """Assert that data validates and serialises back to an equivalent dict."""
        model = self.assert_valid(data)
        dumped = model.model_dump()
        for key, value in data.items():
            self.assertEqual(
                dumped.get(key),
                value,
                f"Roundtrip mismatch on field {key!r}: {value!r} → {dumped.get(key)!r}",
            )


class RegistryTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Base class for tests that need a live CMS instance with a clean database.

    Creates a fresh temporary-file SQLite CMS per test, tears it down after.
    Use ``self.cms`` to access the CMS instance.

    Subclasses should register blocks in ``asyncSetUp`` before calling
    ``super().asyncSetUp()``::

        class TestIntakeBlocks(RegistryTestCase):
            async def asyncSetUp(self):
                await super().asyncSetUp()

                @self.cms.block("jewelry_item")
                class JewelryItem:
                    declared_value: float = NumberField(required=True)
    """

    async def asyncSetUp(self) -> None:
        import tempfile

        from starlette_cms import CMS

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self._db_path = tmp.name

        self.cms = CMS(database_url=f"sqlite:///{self._db_path}", auth="none")
        self._db_context = self.cms.lifespan_context(None)
        await self._db_context.__aenter__()

    async def asyncTearDown(self) -> None:
        import os

        try:
            await self._db_context.__aexit__(None, None, None)
        except Exception:
            pass
        try:
            os.unlink(self._db_path)
        except OSError:
            pass

    def assert_registered(self, block_type: str) -> None:
        """Assert that block_type is in the registry."""
        self.assertIn(
            block_type,
            self.cms.registry,
            f"Block type {block_type!r} is not registered",
        )

    def assert_not_registered(self, block_type: str) -> None:
        """Assert that block_type is NOT in the registry."""
        self.assertNotIn(
            block_type,
            self.cms.registry,
            f"Block type {block_type!r} should not be registered",
        )

    def assert_no_collision(self, block_type: str, new_cls: type) -> None:
        """Assert that registering new_cls as block_type raises BlockRegistrationError."""
        from starlette_cms.exceptions import BlockRegistrationError

        with self.assertRaises(BlockRegistrationError):
            self.cms.registry.register_block(new_cls)
