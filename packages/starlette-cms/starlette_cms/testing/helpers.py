"""Testing helper implementations."""

from __future__ import annotations

import unittest
from typing import Any

from pydantic import ValidationError

from starlette_cms.app import CMS


def validate_block(block_cls: type, data: dict[str, Any]):
    """
    Validate a dict of field values against a block definition.
    Returns the validated Pydantic model instance or raises ValidationError.
    """
    # TODO: implement once Pydantic model generation is wired up
    raise NotImplementedError


class BlockTestCase(unittest.TestCase):
    """TestCase subclass with assertion helpers for block validation."""

    block: type  # set on subclass

    def assert_valid(self, data: dict[str, Any]) -> None:
        try:
            validate_block(self.block, data)
        except ValidationError as e:
            self.fail(f"Expected valid data but got ValidationError: {e}")

    def assert_invalid(self, data: dict[str, Any]) -> None:
        try:
            validate_block(self.block, data)
            self.fail("Expected ValidationError but data was valid.")
        except ValidationError:
            pass

    def assert_fields(self, names: list[str]) -> None:
        # TODO: implement
        raise NotImplementedError

    def assert_field_label(self, field_name: str, label: str) -> None:
        # TODO: implement
        raise NotImplementedError

    def assert_field_required(self, field_name: str) -> None:
        # TODO: implement
        raise NotImplementedError

    def assert_field_optional(self, field_name: str) -> None:
        # TODO: implement
        raise NotImplementedError

    def assert_roundtrip(self, data: dict[str, Any]) -> None:
        # TODO: implement
        raise NotImplementedError


class RegistryTestCase(unittest.TestCase):
    """TestCase subclass with a fresh isolated CMS instance per test."""

    def setUp(self) -> None:
        self.cms = CMS(database_url="sqlite:///:memory:", auth="none")

    def assert_registered(self, block_type: str) -> None:
        self.assertIn(block_type, self.cms.registry)

    def assert_no_collision(self, package: Any, common_blocks: list[str]) -> None:
        for name in common_blocks:
            self.assertNotIn(
                name,
                self.cms.registry,
                f'Package claims common block name "{name}" which may conflict.',
            )
