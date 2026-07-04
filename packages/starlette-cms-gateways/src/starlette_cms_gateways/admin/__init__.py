"""
Gateway admin sub-package.

Exports :class:`GatewayAdmin` — the main entry point for the gateway web UI.
"""

from starlette_cms_gateways.admin.app import GatewayAdmin

__all__ = ["GatewayAdmin"]
