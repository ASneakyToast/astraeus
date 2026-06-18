# API Reference: Field Types

All field types are importable from `starlette_cms`:

```python
from starlette_cms import (
    TextField, RichTextField, ImageField, ListField, BlockField,
    NumberField, SelectField, BoolField, URLField, JSONField, DocumentRef,
)
```

## Base parameters

All fields inherit from `_BaseField` and accept these parameters:

| Parameter | Type | Default |
|---|---|---|
| `required` | `bool` | `False` |
| `label` | `str \| None` | `None` |
| `placeholder` | `str \| None` | `None` |
| `help_text` | `str \| None` | `None` |
| `display_order` | `int \| None` | `None` |
| `group` | `str \| None` | `None` |
| `immutable` | `bool` | `False` |

### `field_meta() -> dict[str, Any]`

Returns the metadata dictionary emitted under `cms:field_meta` in the JSON Schema. Subclasses extend this with type-specific keys.

---

## TextField

```python
TextField(
    required=False, label=None, placeholder=None, help_text=None,
    display_order=None, group=None, immutable=False,
    max_length=None, unique_per_type=False,
)
```

**Pydantic type:** `str` (required) or `str | None` (optional, default `None`)

| Parameter | Type | Default |
|---|---|---|
| `max_length` | `int \| None` | `None` |
| `unique_per_type` | `bool` | `False` |

---

## RichTextField

```python
RichTextField(
    required=False, label=None, placeholder=None, help_text=None,
    display_order=None, group=None, immutable=False,
)
```

**Pydantic type:** `dict` (required) or `dict | None` (optional, default `None`)

Stores ProseMirror document JSON.

---

## ImageField

```python
ImageField(
    required=False, label=None, placeholder=None, help_text=None,
    display_order=None, group=None, immutable=False,
)
```

**Pydantic type:** `str` (required) or `str | None` (optional, default `None`)

When a `MediaBackend` is configured on the CMS, values are validated against the media catalog.

---

## NumberField

```python
NumberField(
    required=False, label=None, placeholder=None, help_text=None,
    display_order=None, group=None, immutable=False,
    min_value=None, max_value=None, precision=None, default=None,
)
```

**Pydantic type:** `float` (required) or `float | None` (optional, default `None`)

| Parameter | Type | Default |
|---|---|---|
| `min_value` | `float \| None` | `None` |
| `max_value` | `float \| None` | `None` |
| `precision` | `int \| None` | `None` |
| `default` | `float \| int \| None` | `None` |

**Extra `field_meta` keys:** `min_value`, `max_value`, `precision` (when set).

---

## SelectField

```python
SelectField(
    required=False, label=None, placeholder=None, help_text=None,
    display_order=None, group=None, immutable=False,
    choices=[], multiple=False,
)
```

**Pydantic type:** `Literal["a", "b", ...]` (required) or `Literal[...] | None` (optional)

| Parameter | Type | Default |
|---|---|---|
| `choices` | `list[str]` | `[]` |
| `multiple` | `bool` | `False` |

**Extra `field_meta` keys:** `choices` (always), `multiple` (when `True`).

---

## BoolField

```python
BoolField(
    required=False, label=None, placeholder=None, help_text=None,
    display_order=None, group=None, immutable=False,
    default=False,
)
```

**Pydantic type:** `bool` (always has a default, never `None`)

| Parameter | Type | Default |
|---|---|---|
| `default` | `bool` | `False` |

**Extra `field_meta` keys:** `default`.

---

## URLField

```python
URLField(
    required=False, label=None, placeholder=None, help_text=None,
    display_order=None, group=None, immutable=False,
    max_length=2048,
)
```

**Pydantic type:** `str` (required) or `str | None` (optional, default `None`)

| Parameter | Type | Default |
|---|---|---|
| `max_length` | `int` | `2048` |

**Extra `field_meta` keys:** `max_length`, `format` (always `"url"`).

---

## JSONField

```python
JSONField(
    required=False, label=None, placeholder=None, help_text=None,
    display_order=None, group=None, immutable=False,
    schema=None,
)
```

**Pydantic type:** `dict | list | None` (always nullable, defaults to `None`)

| Parameter | Type | Default |
|---|---|---|
| `schema` | `dict \| None` | `None` |

**Extra `field_meta` keys:** `schema` (when set).

---

## DocumentRef

```python
DocumentRef(
    required=False, label=None, placeholder=None, help_text=None,
    display_order=None, group=None, immutable=False,
    block_type=None, on_delete="block",
)
```

**Pydantic type:** `str` (required) or `str | None` (optional, default `None`)

Stores the referenced document's nanoid. Validated on create/patch.

| Parameter | Type | Default |
|---|---|---|
| `block_type` | `str \| None` | `None` |
| `on_delete` | `str` | `"block"` |

**`on_delete` values:**

- `"block"` — refuse to delete the referenced document
- `"nullify"` — set this field to `None` in all referencing documents
- `"cascade"` — delete all documents that reference the target

**Extra `field_meta` keys:** `ref_block_type`, `on_delete`, `field_type` (always `"document_ref"`).

---

## ListField

```python
ListField(
    item_type=None, *,
    blocks=None,
    required=False, label=None, placeholder=None, help_text=None,
    display_order=None, group=None, immutable=False,
)
```

**Pydantic type (homogeneous):** `list[T]` where `T` is the `item_type`

**Pydantic type (polymorphic):** `list[Annotated[Union[A, B, ...], Field(discriminator="block_type")]]`

| Parameter | Type | Default |
|---|---|---|
| `item_type` | `Any` | `None` |
| `blocks` | `list[Any] \| None` | `None` |

Pass `item_type` as a positional arg for homogeneous lists, or `blocks=[...]` for polymorphic block lists. Don't pass both.

---

## BlockField

```python
BlockField(
    required=False, label=None, placeholder=None, help_text=None,
    display_order=None, group=None, immutable=False,
    block_type=None,
)
```

**Pydantic type:** The block's Pydantic model class, or `dict` if `block_type` is `dict`.

| Parameter | Type | Default |
|---|---|---|
| `block_type` | `Any` | `None` |
