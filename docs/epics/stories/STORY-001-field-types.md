# STORY-001 — New field types: Number, Select, Bool, URL, JSON

**Epic:** [EPIC-001](../EPIC-001-vpp-mvp.md)  
**Status:** Ready  
**Depends on:** Nothing (first story)  
**Blocks:** STORY-002, STORY-003, STORY-004

---

## Goal

Add five field types to `starlette_cms/fields.py` and wire them through `model_builder.py` so
they generate correct Pydantic models and expose their metadata via `GET /api/schema/{type}`.

These are the minimum field types required to write the VPP `JewelryItem`, `BikeItem`, and
`StorageRates` blocks.

---

## Field specifications

### `NumberField`

```python
@dataclass
class NumberField(_BaseField):
    min_value: float | None = None
    max_value: float | None = None
    precision: int | None = None     # decimal places for display/storage hint
    default: float | int | None = None
```

- Pydantic type: `float` (required) or `float | None` (optional)
- `min_value` / `max_value` → `Field(ge=min_value, le=max_value, ...)` on the Pydantic field
- `default` → `Field(default=default, ...)` when provided; overrides optional→None behaviour
- `field_meta()` includes: `label`, `min_value`, `max_value`, `precision`, `help_text`

### `SelectField`

```python
@dataclass
class SelectField(_BaseField):
    choices: list[str] = field(default_factory=list)
    multiple: bool = False   # future — not enforced in v1, just metadata
```

- Pydantic type: `Literal[*choices]` (required) or `Literal[*choices] | None` (optional)
- When `choices` is empty → fall back to `str` (graceful degradation, log a warning)
- `field_meta()` includes: `label`, `choices`, `multiple`

### `BoolField`

```python
@dataclass
class BoolField(_BaseField):
    default: bool = False
```

- Pydantic type: always `bool` (never None — default covers the optional case)
- `Field(default=self.default, ...)` always
- `field_meta()` includes: `label`, `default`

### `URLField`

```python
@dataclass
class URLField(_BaseField):
    max_length: int = 2048
```

- Pydantic type: `str` (required) or `str | None` (optional)
- No Pydantic URL validation in v1 — raw string. Add `AnyUrl` in a future story if needed.
- `field_meta()` includes: `label`, `max_length`, `format: "url"` (for form renderers)

### `JSONField`

```python
@dataclass
class JSONField(_BaseField):
    schema: dict | None = None   # optional JSON Schema for the blob — not enforced v1
```

- Pydantic type: `dict | list | None` (always optional — JSON blobs default to None)
  or `dict | list` when `required=True`
- `field_meta()` includes: `label`, `schema` (when provided)

---

## model_builder.py changes

`_make_field()` needs new `isinstance` branches for each new field type, before the fallback:

```python
if isinstance(default, NumberField):
    validators = {}
    if default.min_value is not None:
        validators["ge"] = default.min_value
    if default.max_value is not None:
        validators["le"] = default.max_value
    field_default = default.default if default.default is not None else (None if optional else ...)
    return (float | None if optional else float, Field(default=field_default, json_schema_extra=extra, **validators))

if isinstance(default, SelectField):
    from typing import Literal
    lit = Literal[tuple(default.choices)] if default.choices else str
    if optional:
        return (lit | None, Field(default=None, json_schema_extra=extra))
    return (lit, Field(..., json_schema_extra=extra))

if isinstance(default, BoolField):
    return (bool, Field(default=default.default, json_schema_extra=extra))

if isinstance(default, URLField):
    if optional:
        return (str | None, Field(default=None, json_schema_extra=extra))
    return (str, Field(..., json_schema_extra=extra))

if isinstance(default, JSONField):
    json_type: Any = dict | list | None
    if not optional:
        json_type = dict | list
        return (json_type, Field(..., json_schema_extra=extra))
    return (json_type, Field(default=None, json_schema_extra=extra))
```

Import `NumberField`, `SelectField`, `BoolField`, `URLField`, `JSONField` at the top of
`model_builder.py` (currently only `TextField`, `RichTextField`, `ImageField`, `ListField`,
`BlockField` are imported).

---

## `__init__.py` exports

Add all five new field types to `starlette_cms/__init__.py` public exports.

---

## schema.py changes

`GET /api/schema/{block_type}` already serialises `cms:field_meta` from each field's
`field_meta()` method. No endpoint changes needed — just ensure each new `field_meta()`
method returns all relevant keys and they appear in the JSON Schema output.

Verify with a test that `GET /api/schema/jewelry_item` returns:
```json
{
  "properties": {
    "storage_location": {
      "cms:field_meta": {
        "label": "Storage Location",
        "choices": ["bank_vault", "home_safe", "standard", "daily_wear"]
      }
    }
  }
}
```

---

## Tests

### `tests/test_block_decorator.py` additions

- `test_number_field_required` — validates float, rejects string
- `test_number_field_optional_defaults_none` — omitting field → None
- `test_number_field_min_max` — value below min_value raises ValidationError
- `test_number_field_with_default` — default flows through to Pydantic
- `test_select_field_required` — rejects value not in choices
- `test_select_field_optional` — None is valid
- `test_bool_field_default_false` — omitting field gives False
- `test_bool_field_explicit_true` — True validates
- `test_url_field_required` — any string passes in v1
- `test_json_field_accepts_dict` — dict validates
- `test_json_field_accepts_list` — list validates
- `test_json_field_optional_defaults_none`

### `tests/test_schema.py` additions

- `test_select_field_schema_includes_choices` — `cms:field_meta.choices` present
- `test_number_field_schema_includes_precision` — `cms:field_meta.precision` present
- `test_url_field_schema_includes_format` — `cms:field_meta.format == "url"`

---

## Definition of done

- [ ] All five field types defined in `fields.py`
- [ ] All five wired through `_make_field()` in `model_builder.py`
- [ ] All five exported from `starlette_cms/__init__.py`
- [ ] `field_meta()` returns all documented keys for each type
- [ ] All tests above pass
- [ ] `uv run pyright packages/starlette-cms/` — zero new errors
- [ ] No regressions in existing tests
