"""
Feedback admin sub-package.

Exports :class:`FeedbackAdmin` — the main entry point for the feedback web UI.
"""

from starlette_cms_feedback.admin.app import FeedbackAdmin

__all__ = ["FeedbackAdmin"]
