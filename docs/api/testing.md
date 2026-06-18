# API Reference: Testing Utilities

```python
from starlette_cms.testing import validate_block, BlockTestCase, RegistryTestCase
```

---

## `validate_block(block_cls, data) -> pydantic.BaseModel`

Validate a dict against a block class. Builds the Pydantic model if the class is not already one.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `block_cls` | `type` | A block class (decorated with `@block` or `@cms.block`) |
| `data` | `dict` | Data to validate against the block schema |

**Returns:** The validated Pydantic model instance.

**Raises:** `pydantic.ValidationError` if the data fails validation.

```python
from starlette_cms.testing import validate_block

result = validate_block(HeroBlock, {"title": "Hello"})
assert result.title == "Hello"

# Invalid data raises ValidationError
import pytest
with pytest.raises(pydantic.ValidationError):
    validate_block(HeroBlock, {"title": 42})
```

---

## BlockTestCase

`unittest.TestCase` subclass for testing block definitions.

### Class attributes

| Attribute | Type | Required | Description |
|---|---|---|---|
| `block_cls` | `type` | yes | The block class to test |
| `valid_data` | `dict` | no | Default valid data (used by `assert_roundtrip`, etc.) |

The `setUp()` method automatically builds the Pydantic model from `block_cls`.

### Methods

#### `assert_valid(data) -> pydantic.BaseModel`

Assert that `data` validates against the block schema. Returns the model instance.

```python
def test_valid(self):
    result = self.assert_valid({"title": "Hello", "price": 9.99})
    assert result.title == "Hello"
```

#### `assert_invalid(data, *, field=None)`

Assert that `data` fails validation. If `field` is provided, also assert the error is on that specific field.

```python
def test_missing_required(self):
    self.assert_invalid({}, field="title")

def test_wrong_type(self):
    self.assert_invalid({"title": 42}, field="title")
```

#### `assert_fields(*field_names)`

Assert all named fields exist on the model.

```python
def test_has_fields(self):
    self.assert_fields("title", "subtitle", "image")
```

#### `assert_field_label(field_name, expected_label)`

Assert a field's `cms:field_meta` label matches the expected value.

```python
def test_labels(self):
    self.assert_field_label("title", "Headline")
```

#### `assert_field_required(field_name)`

Assert the field appears in the JSON schema's `required` list.

```python
def test_title_required(self):
    self.assert_field_required("title")
```

#### `assert_field_optional(field_name)`

Assert the field does not appear in the JSON schema's `required` list.

```python
def test_subtitle_optional(self):
    self.assert_field_optional("subtitle")
```

#### `assert_roundtrip(data)`

Assert data validates and serializes back to an equivalent dict. Useful for checking that no data is lost during validation.

```python
def test_roundtrip(self):
    self.assert_roundtrip({"title": "Hello", "subtitle": "World"})
```

---

## RegistryTestCase

`unittest.IsolatedAsyncioTestCase` subclass for integration tests that need a live CMS instance with a database.

### Lifecycle

- `asyncSetUp()` — creates a fresh temporary SQLite database and CMS instance at `self.cms`
- `asyncTearDown()` — cleans up the database

Register blocks in `asyncSetUp()` before calling `super().asyncSetUp()`:

```python
class TestMyBlocks(RegistryTestCase):

    async def asyncSetUp(self):
        @self.cms.block("article")
        class Article:
            title: str = TextField(required=True)

        await super().asyncSetUp()
```

### Methods

#### `assert_registered(block_type)`

Assert the block type is in the registry.

```python
async def test_registered(self):
    self.assert_registered("article")
```

#### `assert_not_registered(block_type)`

Assert the block type is not in the registry.

```python
async def test_not_registered(self):
    self.assert_not_registered("nonexistent")
```

#### `assert_no_collision(block_type, new_cls)`

Assert that registering `new_cls` under `block_type` raises `BlockRegistrationError`.

```python
async def test_collision(self):
    self.assert_no_collision("article", DuplicateArticle)
```
