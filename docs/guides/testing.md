# Testing Your Blocks

starlette-cms provides testing utilities for validating block definitions without starting a server.

```python
from starlette_cms.testing import validate_block, BlockTestCase, RegistryTestCase
```

## Quick validation with `validate_block()`

For one-off checks, `validate_block()` validates a dict against a block class:

```python
from starlette_cms.testing import validate_block

result = validate_block(HeroBlock, {"title": "Hello", "subtitle": "World"})
assert result.title == "Hello"
```

It returns the validated Pydantic model instance. Raises `pydantic.ValidationError` on failure.

## BlockTestCase

For systematic testing of a block definition, subclass `BlockTestCase`:

```python
import unittest
from starlette_cms import TextField, NumberField, SelectField
from starlette_cms import CMS
from starlette_cms.testing import BlockTestCase

cms = CMS(database_url="sqlite:///test.db")

@cms.block("jewelry_item")
class JewelryItem:
    name: str = TextField(required=True, label="Item Name")
    price: float = NumberField(required=True, min_value=0.0, label="Price")
    material: str = SelectField(
        choices=["gold", "silver", "platinum"],
        required=True,
    )
    description: str = TextField()


class TestJewelryItem(BlockTestCase):
    block_cls = JewelryItem
    valid_data = {
        "name": "Diamond Ring",
        "price": 999.99,
        "material": "gold",
    }

    def test_valid_item(self):
        result = self.assert_valid(self.valid_data)
        assert result.name == "Diamond Ring"

    def test_missing_name_is_invalid(self):
        self.assert_invalid(
            {"price": 100.0, "material": "silver"},
            field="name",
        )

    def test_bad_material_is_invalid(self):
        self.assert_invalid(
            {"name": "Ring", "price": 100.0, "material": "wood"},
            field="material",
        )

    def test_has_expected_fields(self):
        self.assert_fields("name", "price", "material", "description")

    def test_labels(self):
        self.assert_field_label("name", "Item Name")
        self.assert_field_label("price", "Price")

    def test_required_fields(self):
        self.assert_field_required("name")
        self.assert_field_required("price")
        self.assert_field_required("material")
        self.assert_field_optional("description")

    def test_roundtrip(self):
        self.assert_roundtrip(self.valid_data)
```

### BlockTestCase methods

| Method | Description |
|---|---|
| `assert_valid(data)` | Assert data validates. Returns the model instance |
| `assert_invalid(data, *, field=None)` | Assert data fails. Optionally check the error is on a specific field |
| `assert_fields(*names)` | Assert all named fields exist on the model |
| `assert_field_label(field, label)` | Assert a field's `cms:field_meta` label matches |
| `assert_field_required(field)` | Assert field is in the JSON schema's `required` list |
| `assert_field_optional(field)` | Assert field is not required |
| `assert_roundtrip(data)` | Assert data validates and serializes back to an equivalent dict |

## RegistryTestCase

For integration tests that need a running CMS with a database, use `RegistryTestCase`:

```python
from starlette_cms.testing import RegistryTestCase
from starlette_cms import TextField


class TestMyRegistry(RegistryTestCase):

    async def asyncSetUp(self):
        @self.cms.block("article")
        class ArticleBlock:
            title: str = TextField(required=True)

        await super().asyncSetUp()

    async def test_block_is_registered(self):
        self.assert_registered("article")

    async def test_unknown_block_not_registered(self):
        self.assert_not_registered("nonexistent")
```

`RegistryTestCase` creates a fresh temporary SQLite database for every test and tears it down after. `self.cms` is a live CMS instance.

### RegistryTestCase methods

| Method | Description |
|---|---|
| `assert_registered(block_type)` | Assert block type is in the registry |
| `assert_not_registered(block_type)` | Assert block type is not in the registry |
| `assert_no_collision(block_type, new_cls)` | Assert registering `new_cls` raises `BlockRegistrationError` |

## Testing HTTP endpoints

For endpoint-level integration tests, use `httpx.AsyncClient` with `ASGITransport`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from starlette_cms import CMS, TextField


@pytest.fixture
async def client():
    cms = CMS(database_url="sqlite:///test.db")

    @cms.block("note")
    class NoteBlock:
        title: str = TextField(required=True)

    async with cms.lifespan_context(None):
        transport = ASGITransport(app=cms.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_create_document(client):
    response = await client.post("/api/documents", json={
        "doc_type": "note",
        "body": {"title": "Test note"},
    })
    assert response.status_code == 201
    assert response.json()["body"]["title"] == "Test note"
```
