"""Tests for starlette_cms.testing helpers."""

from __future__ import annotations

import pydantic
import pytest
from starlette_cms.fields import TextField
from starlette_cms.registry import block
from starlette_cms.testing import BlockTestCase, RegistryTestCase, validate_block

# ---------------------------------------------------------------------------
# A simple block used throughout these tests
# ---------------------------------------------------------------------------


@block("sample")
class SampleBlock:
    title: str = TextField(required=True, label="Title")
    subtitle: str = TextField(label="Subtitle")


# ---------------------------------------------------------------------------
# validate_block()
# ---------------------------------------------------------------------------


def test_validate_block_valid_data():
    model = validate_block(SampleBlock, {"title": "Hello"})
    assert model.title == "Hello"  # type: ignore[attr-defined]


def test_validate_block_invalid_data():
    with pytest.raises(pydantic.ValidationError):
        # title is required
        validate_block(SampleBlock, {"subtitle": "no title"})


def test_validate_block_with_pydantic_model_subclass():
    """validate_block should accept an already-built Pydantic model directly."""
    from starlette_cms.model_builder import build_block_model

    model_cls = build_block_model("sample2", SampleBlock)
    instance = validate_block(model_cls, {"title": "Direct"})
    assert instance.title == "Direct"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# BlockTestCase assertion helpers
# ---------------------------------------------------------------------------


class SampleBlockTests(BlockTestCase):
    block_cls = SampleBlock
    valid_data = {"title": "Good title"}


class TestBlockTestCaseAssertValid(SampleBlockTests):
    def test_assert_valid_passes_on_good_data(self):
        model = self.assert_valid({"title": "Good"})
        assert model.title == "Good"  # type: ignore[attr-defined]


class TestBlockTestCaseAssertInvalid(SampleBlockTests):
    def test_assert_invalid_catches_validation_error(self):
        # Missing required 'title' field should fail
        self.assert_invalid({"subtitle": "no title"})

    def test_assert_invalid_specific_field(self):
        self.assert_invalid({"subtitle": "no title"}, field="title")

    def test_assert_invalid_passes_when_expected_field_has_error(self):
        # Providing a non-string value for a str field triggers an error on "title"
        self.assert_invalid({"title": None}, field="title")


class TestBlockTestCaseAssertFields(SampleBlockTests):
    def test_assert_fields_present(self):
        self.assert_fields("title", "subtitle")

    def test_assert_fields_missing_raises(self):
        with self.assertRaises(AssertionError):
            self.assert_fields("nonexistent_field")


class TestBlockTestCaseFieldLabel(SampleBlockTests):
    def test_assert_field_label_correct(self):
        self.assert_field_label("title", "Title")

    def test_assert_field_label_subtitle(self):
        self.assert_field_label("subtitle", "Subtitle")

    def test_assert_field_label_wrong_raises(self):
        with self.assertRaises(AssertionError):
            self.assert_field_label("title", "Wrong Label")


class TestBlockTestCaseRequired(SampleBlockTests):
    def test_assert_field_required(self):
        self.assert_field_required("title")

    def test_assert_field_required_raises_for_optional(self):
        with self.assertRaises(AssertionError):
            self.assert_field_required("subtitle")


class TestBlockTestCaseOptional(SampleBlockTests):
    def test_assert_field_optional(self):
        self.assert_field_optional("subtitle")

    def test_assert_field_optional_raises_for_required(self):
        with self.assertRaises(AssertionError):
            self.assert_field_optional("title")


class TestBlockTestCaseRoundtrip(SampleBlockTests):
    def test_assert_roundtrip(self):
        self.assert_roundtrip({"title": "Round-trip value"})

    def test_assert_roundtrip_with_optional(self):
        # subtitle is optional; when omitted it round-trips as None
        model = self.assert_valid({"title": "Hello"})
        dumped = model.model_dump()
        assert dumped["subtitle"] is None


# ---------------------------------------------------------------------------
# RegistryTestCase
# ---------------------------------------------------------------------------


class TestRegistryTestCaseFreshDb(RegistryTestCase):
    """Each test should get a clean CMS instance."""

    async def test_fresh_db_no_blocks(self):
        # No blocks registered yet — registry should be empty
        self.assertEqual(self.cms.registry.names(), [])

    async def test_can_register_block(self):
        @self.cms.block("widget")
        class WidgetBlock:
            label: str = TextField(required=True)

        self.assert_registered("widget")


class TestRegistryTestCaseAssertRegistered(RegistryTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()

        @self.cms.block("badge")
        class BadgeBlock:
            text: str = TextField(required=True)

    async def test_assert_registered(self):
        self.assert_registered("badge")

    async def test_assert_not_registered(self):
        self.assert_not_registered("nonexistent")


class TestRegistryTestCaseNoCollision(RegistryTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()

        @self.cms.block("card")
        class CardBlock:
            title: str = TextField(required=True)

    async def test_assert_no_collision_raises(self):
        @block("card")
        class CardBlockDuplicate:
            body: str = TextField(required=True)

        # assert_no_collision expects a BlockRegistrationError when registering the dup
        self.assert_no_collision("card", CardBlockDuplicate)
