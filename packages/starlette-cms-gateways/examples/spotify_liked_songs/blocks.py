"""
Block definition for Spotify liked songs.

Register this block in your application before starting the CMS::

    from examples.spotify_liked_songs.blocks import SpotifyLikedSongBlock
    cms.register_block(SpotifyLikedSongBlock)

Or use the standalone ``@block()`` decorator form (shown here) and call
``SpotifyLikedSongBlock`` after importing to trigger registration::

    from starlette_cms import CMS
    from examples.spotify_liked_songs.blocks import SpotifyLikedSongBlock
    cms.register_block(SpotifyLikedSongBlock)
"""

from __future__ import annotations

from starlette_cms.fields import TextField, URLField
from starlette_cms.registry import block


@block("spotify_liked_song")
class SpotifyLikedSongBlock:
    """
    A single Spotify liked song entry.

    Mutable by default — annotate via MCP or editor after sync (add notes,
    curate, tag).  To create an immutable audit trail instead, set
    ``append_only=True`` on the block and ``immutable = True`` on the gateway.
    """

    track_name: str = TextField(label="Track Name")
    artist_name: str = TextField(label="Artist")
    album_name: str = TextField(label="Album", required=False)
    spotify_url: str = URLField(label="Spotify URL")
    liked_at: str = TextField(label="Liked At (ISO 8601)")
