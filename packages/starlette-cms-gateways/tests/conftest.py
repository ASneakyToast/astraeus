"""
Shared pytest configuration for starlette-cms-gateways tests.

Adds the ``examples/`` directory to ``sys.path`` so that example gateways
(spotify_liked_songs, inaturalist_outings) can be imported without being
installed as packages.
"""

from __future__ import annotations

import sys
from pathlib import Path

# examples/ lives two levels up from this conftest.py
_EXAMPLES_DIR = Path(__file__).parent.parent / "examples"
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))
