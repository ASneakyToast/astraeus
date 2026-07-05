"""
Gateway discovery — shared between the CLI and the admin API.

Separated from ``cli.py`` so that non-CLI code (e.g. the admin web UI) can
import gateway discovery without pulling in Click or terminal logging config.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def discover_gateways() -> dict[str, Any]:
    """
    Return a dict of ``{entry_point_name: gateway_class}`` for all installed
    gateways registered under the ``starlette_cms_gateways.gateways`` group.

    Gateways that fail to load (e.g. missing dependency) are skipped with a
    warning — they do not prevent other gateways from loading.

    Register a gateway in ``pyproject.toml``::

        [project.entry-points."starlette_cms_gateways.gateways"]
        my-gateway = "myapp.gateways:MyGateway"
    """
    eps = entry_points(group="starlette_cms_gateways.gateways")
    result: dict[str, Any] = {}
    for ep in eps:
        try:
            cls = ep.load()
            result[ep.name] = cls
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "starlette_cms_gateways.discovery.gateway_load_failed",
                gateway=ep.name,
                exc_info=exc,
            )
    return result
