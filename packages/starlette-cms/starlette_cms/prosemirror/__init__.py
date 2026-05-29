"""
Optional ProseMirror bridge — activated by starlette-editor at mount time.

This module is present in the package but has no runtime effect unless
explicitly instantiated. starlette-editor imports and activates it.
"""

from starlette_cms.prosemirror.bridge import ProseMirrorBridge

__all__ = ["ProseMirrorBridge"]
