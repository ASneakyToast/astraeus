# STORY-006 — Phase 4 testing utilities

**Epic:** [EPIC-001](../EPIC-001-vpp-mvp.md)  
**Status:** Ready  
**Depends on:** STORY-001 (new field types needed for `BlockTestCase` examples)  
**Blocks:** Nothing (independent)

---

## Goal

Implement the Phase 4 testing utilities per the roadmap: `validate_block()`, `BlockTestCase`,
and complete `RegistryTestCase`. These make it straightforward to test block definitions and
ensure every block in `contrib/blocks/` has test coverage.

---

## Changes required

### `starlette_cms/testing/helpers.py`

Current state: `RegistryTestCase` is stubbed. Implement it fully and add `BlockTestCase`.

```python
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
```

#### `validate_block(block_cls, data)`

```python
def validate_block(block_cls: type, data: dict) -> pydantic.BaseModel:
    """
    Validate ``data`` against ``block_cls``, returning the model instance on success
    or raising ``pydantic.ValidationError`` on failure.

    Builds the Pydantic model from the class if not already built.

    Example::

        model = validate_block(JewelryItem, {"declared_value": 8000, "storage_location": "home_safe"})
        assert model.declared_value == 8000.0
    """
    from starlette_cms.model_builder import build_block_model
    import pydantic

    if not (isinstance(block_cls, type) and issubclass(block_cls, pydantic.BaseModel)):
        name = getattr(block_cls, "__block_type__", block_cls.__name__.lower())
        model_cls = build_block_model(name, block_cls)
    else:
        model_cls = block_cls

    return model_cls.model_validate(data)
```

#### `BlockTestCase`

A `unittest.TestCase` subclass with assertion helpers:

```python
class BlockTestCase(unittest.TestCase):
    """
    Base class for block definition tests.

    Subclasses must set ``block_cls`` and ``valid_data``.

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
    valid_data: dict = {}

    def setUp(self):
        from starlette_cms.model_builder import build_block_model
        import pydantic
        if not (isinstance(self.block_cls, type) and issubclass(self.block_cls, pydantic.BaseModel)):
            name = getattr(self.block_cls, "__block_type__", self.block_cls.__name__.lower())
            self._model = build_block_model(name, self.block_cls)
        else:
            self._model = self.block_cls

    def assert_valid(self, data: dict) -> pydantic.BaseModel:
        """Assert that data validates successfully. Returns the model instance."""
        return self._model.model_validate(data)

    def assert_invalid(self, data: dict, *, field: str | None = None) -> None:
        """Assert that data fails validation. Optionally assert the error is on a specific field."""
        import pydantic
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
        self.assertEqual(actual, expected_label,
                         f"Field {field_name!r}: expected label {expected_label!r}, got {actual!r}")

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

    def assert_roundtrip(self, data: dict) -> None:
        """Assert that data validates and serialises back to an equivalent dict."""
        model = self.assert_valid(data)
        dumped = model.model_dump()
        for key, value in data.items():
            self.assertEqual(dumped.get(key), value,
                             f"Roundtrip mismatch on field {key!r}: {value!r} → {dumped.get(key)!r}")
```

#### `RegistryTestCase` (complete implementation)

```python
class RegistryTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Base class for tests that need a live CMS instance with a clean database.

    Creates a fresh in-memory SQLite CMS per test, tears it down after.
    Use ``self.cms`` to access the CMS instance.

    Subclasses should register blocks in ``setUp`` before calling ``super().asyncSetUp()``::

        class TestIntakeBlocks(RegistryTestCase):
            async def asyncSetUp(self):
                @self.cms.block("jewelry_item")
                class JewelryItem:
                    declared_value: NumberField(required=True)
                await super().asyncSetUp()
    """

    async def asyncSetUp(self):
        from starlette_cms import CMS
        self.cms = CMS(database_url="sqlite://:memory:", auth="none")
        await self.cms._db.create_tables()

    async def asyncTearDown(self):
        await self.cms._db.close()

    def assert_registered(self, block_type: str) -> None:
        self.assertIn(block_type, self.cms.registry,
                      f"Block type {block_type!r} is not registered")

    def assert_not_registered(self, block_type: str) -> None:
        self.assertNotIn(block_type, self.cms.registry,
                         f"Block type {block_type!r} should not be registered")

    def assert_no_collision(self, block_type: str, new_cls: type) -> None:
        """Assert that registering new_cls as block_type raises BlockRegistrationError."""
        from starlette_cms.exceptions import BlockRegistrationError
        with self.assertRaises(BlockRegistrationError):
            self.cms.registry.register_block(new_cls)
```

### `starlette_cms/testing/__init__.py`

Export all three:

```python
from starlette_cms.testing.helpers import (
    BlockTestCase,
    RegistryTestCase,
    validate_block,
)

__all__ = ["BlockTestCase", "RegistryTestCase", "validate_block"]
```

### `contrib/blocks/basic.py` tests

Add `tests/test_contrib_blocks.py` using `BlockTestCase` for all blocks in
`starlette_cms/contrib/blocks/basic.py`.

---

## Tests

### `tests/test_testing_helpers.py` (new file)

- `test_validate_block_valid_data` — returns model on valid input
- `test_validate_block_invalid_data` — raises ValidationError on bad input
- `test_block_test_case_assert_valid` — passes on good data
- `test_block_test_case_assert_invalid` — catches ValidationError
- `test_block_test_case_assert_invalid_specific_field` — checks error field
- `test_block_test_case_assert_fields` — all named fields present
- `test_block_test_case_assert_field_label` — label from field_meta
- `test_block_test_case_assert_field_required` — required field
- `test_block_test_case_assert_field_optional` — optional field
- `test_block_test_case_assert_roundtrip` — data survives model_validate + model_dump
- `test_registry_test_case_fresh_db` — each test gets clean state
- `test_registry_test_case_assert_registered`
- `test_registry_test_case_assert_no_collision`

---

## Definition of done

- [ ] `validate_block(block_cls, data)` helper implemented
- [ ] `BlockTestCase` with all 7 assert methods
- [ ] `RegistryTestCase` fully implemented (not just stubbed)
- [ ] All three exported from `starlette_cms.testing`
- [ ] `tests/test_testing_helpers.py` tests all pass
- [ ] `contrib/blocks/basic.py` blocks covered by `BlockTestCase` tests
- [ ] No regressions
