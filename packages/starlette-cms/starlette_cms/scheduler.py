"""
Scheduler — publish changesets whose ``publish_at`` is in the past.

Designed to be called from a cron job or CLI command::

    from starlette_cms.scheduler import check_scheduled_changesets

    published_ids = await check_scheduled_changesets(cms)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from starlette_cms.tables import CMSChangeset

if TYPE_CHECKING:
    from starlette_cms.app import CMS

logger = structlog.get_logger(__name__)


async def check_scheduled_changesets(cms: CMS) -> list[str]:
    """
    Publish any changesets whose ``publish_at`` is in the past.

    Returns a list of changeset IDs that were published.
    Designed to be called from a cron job or CLI command.

    :param cms: The CMS instance to publish against.
    :returns: List of changeset IDs that were published.
    """
    from starlette_cms.api.changesets import _publish_changeset_logic

    now = datetime.now(UTC)

    due_rows = (
        await CMSChangeset.select()
        .where(
            CMSChangeset.status == "scheduled",
            CMSChangeset.publish_at <= now,
        )
        .run()
    )

    published_ids: list[str] = []
    for row in due_rows:
        changeset_id = row["id"]
        try:
            result = await _publish_changeset_logic(changeset_id, cms)
            if result is not None:
                published_ids.append(changeset_id)
                logger.info(
                    "starlette_cms.scheduler.changeset_published",
                    changeset_id=changeset_id,
                    title=row.get("title", ""),
                )
        except Exception as exc:
            logger.error(
                "starlette_cms.scheduler.publish_failed",
                changeset_id=changeset_id,
                exc_info=exc,
            )

    return published_ids
