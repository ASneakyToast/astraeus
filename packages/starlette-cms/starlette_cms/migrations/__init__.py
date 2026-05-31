"""
Schema migration runner for starlette-cms.

Migrations are registered on a ``CMS`` instance using the ``@cms.migration``
decorator and stored as ``{from_version, to_version, fn}`` dicts. This module
builds the chain from the current stored version to the target version and
runs each step in order.

Usage::

    cms = CMS(database_url="sqlite:///content.db", auth="none")

    @cms.migration(from_version="0.3.0", to_version="0.4.0")
    async def migrate_0_3_to_0_4(db):
        # db is the CMSDatabase instance
        await db.run_ddl("ALTER TABLE cms_document ADD COLUMN ...")

    # In CLI / startup code:
    runner = MigrationRunner(cms)
    pending = runner.pending(current_version="0.3.0", target_version="0.4.0")
    await runner.run(pending, dry_run=False)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starlette_cms.app import CMS


@dataclass
class MigrationStep:
    """A single registered migration step."""

    from_version: str
    to_version: str
    fn: Any  # async callable(db) -> None


class MigrationError(Exception):
    """Raised when the migration chain is broken or ambiguous."""


class MigrationRunner:
    """
    Builds and executes the migration chain for a CMS instance.

    :param cms: The CMS instance whose ``_migrations`` list is used.
    """

    def __init__(self, cms: CMS) -> None:
        self._cms = cms

    def _all_steps(self) -> list[MigrationStep]:
        return [
            MigrationStep(
                from_version=m["from_version"],
                to_version=m["to_version"],
                fn=m["fn"],
            )
            for m in self._cms._migrations
        ]

    def pending(self, *, current_version: str, target_version: str) -> list[MigrationStep]:
        """
        Return the ordered list of migration steps needed to go from
        ``current_version`` to ``target_version``.

        Raises ``MigrationError`` if the chain is broken (a step is missing).

        Returns ``[]`` if ``current_version == target_version``.
        """
        if current_version == target_version:
            return []

        # Build a lookup: from_version → step
        by_from: dict[str, MigrationStep] = {}
        for step in self._all_steps():
            if step.from_version in by_from:
                raise MigrationError(
                    f"Ambiguous migration: two steps both start from "
                    f"{step.from_version!r}. Remove the duplicate."
                )
            by_from[step.from_version] = step

        # Walk the chain
        chain: list[MigrationStep] = []
        cursor = current_version
        visited: set[str] = set()

        while cursor != target_version:
            if cursor in visited:
                raise MigrationError(f"Cycle detected in migration chain at version {cursor!r}.")
            visited.add(cursor)

            step = by_from.get(cursor)
            if step is None:
                raise MigrationError(
                    f"No migration registered from {cursor!r}. "
                    f"Cannot reach target version {target_version!r}."
                )
            chain.append(step)
            cursor = step.to_version

        return chain

    async def run(
        self,
        steps: list[MigrationStep],
        *,
        dry_run: bool = False,
    ) -> list[MigrationStep]:
        """
        Execute a list of migration steps in order.

        After each step the ``schema_version`` in ``cms_meta`` is updated.
        On ``dry_run=True`` the functions are not called and the database is
        not modified, but the chain is validated and returned as-is.

        :param steps: Ordered list of steps, as returned by ``pending()``.
        :param dry_run: If True, skip execution and DB updates.
        :returns: The list of steps that were (or would be) applied.
        """
        if dry_run:
            return steps

        from starlette_cms.tables import CMSMeta

        db = self._cms._db  # set by lifespan_context

        for step in steps:
            # Call the migration function
            result = step.fn(db)
            if hasattr(result, "__await__"):
                await result

            # Update stored schema_version
            existing = await CMSMeta.select().where(CMSMeta.key == "schema_version").run()
            if existing:
                await (
                    CMSMeta.update({CMSMeta.value: step.to_version})
                    .where(CMSMeta.key == "schema_version")
                    .run()
                )
            else:
                await CMSMeta.insert(CMSMeta(key="schema_version", value=step.to_version)).run()

        return steps
