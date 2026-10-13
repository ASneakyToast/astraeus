"""
starlette-cms-feedback — feedback and bug reports for a starlette-cms instance.

File, list and triage reports through an admin page, an HTTP API on the CMS,
or MCP tools.  Reports live in their own SQLite database and are only ever
served through auth-checked routes.

Quickstart::

    from starlette_cms import CMS
    from starlette_cms_feedback import FeedbackAdmin

    cms = CMS(database_url="sqlite:///content.db", auth="apikey", api_key="secret")
    feedback = FeedbackAdmin(cms=cms, db_path="feedback.db")

    # Mount cms.app at /cms and feedback.app at /feedback.
"""

from __future__ import annotations

import logging as _logging

from starlette_cms_feedback.admin import FeedbackAdmin
from starlette_cms_feedback.models import (
    FeedbackCreate,
    FeedbackKind,
    FeedbackReport,
    FeedbackSeverity,
    FeedbackStatus,
    FeedbackUpdate,
)
from starlette_cms_feedback.store import FeedbackStore

# Library contract: install NullHandler so the host app controls log routing.
# See ADR 017.
_logging.getLogger("starlette_cms_feedback").addHandler(_logging.NullHandler())

__version__ = "0.1.0"

__all__ = [
    "FeedbackAdmin",
    "FeedbackCreate",
    "FeedbackKind",
    "FeedbackReport",
    "FeedbackSeverity",
    "FeedbackStatus",
    "FeedbackStore",
    "FeedbackUpdate",
]
