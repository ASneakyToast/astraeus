"""
Example gateway: Spotify Liked Songs

Pulls liked tracks from the Spotify Web API and creates one CMS document per
track using the ``spotify_liked_song`` block type.

This is a **reference implementation** — it lives in examples/ and is not
installed as part of starlette-cms-gateways.  Copy it into your own application
and adapt to your needs.

Dependencies (not declared in the package):
- spotipy >= 2.23 (pip install spotipy)

Setup:
    export SPOTIPY_CLIENT_ID=...
    export SPOTIPY_CLIENT_SECRET=...
    export SPOTIPY_REDIRECT_URI=http://localhost:8888/callback

    # Authorise once (saves token to .cache):
    python -c "
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    sp = spotipy.Spotify(auth_manager=SpotifyOAuth(scope='user-library-read'))
    "

Register in your pyproject.toml::

    [project.entry-points."starlette_cms_gateways.gateways"]
    spotify-liked-songs = "myapp.gateways.spotify_liked_songs:SpotifyLikedSongsGateway"

Then sync::

    gateways sync spotify-liked-songs \\
        --cms-url https://cms.example.com \\
        --api-key $CMS_API_KEY
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from starlette_cms_gateways import BaseGateway, GatewayItem


class SpotifyLikedSongsGateway(BaseGateway):
    """
    Sync Spotify liked songs into starlette-cms.

    Each liked track becomes one document of block type ``spotify_liked_song``.
    Documents are auto-published on creation.

    Manages its own cursor state internally if incremental sync is needed.
    """

    service_name = "spotify_liked_songs"
    block_type = "spotify_liked_song"
    auto_publish = True

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Initialise the Spotipy client.  Credentials are read from env vars:
        # SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI.
        # The token cache is written to .cache in the working directory.
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth

            self._sp = spotipy.Spotify(
                auth_manager=SpotifyOAuth(scope="user-library-read")
            )
        except ImportError as exc:
            raise ImportError(
                "SpotifyLikedSongsGateway requires spotipy. "
                "Install it with: pip install spotipy"
            ) from exc

    async def fetch(self) -> AsyncIterator[GatewayItem]:
        """
        Yield liked tracks from Spotify, newest first.

        Note: Spotipy's API is synchronous — we call it in a thread-pool via
        ``asyncio.to_thread`` to avoid blocking the event loop.
        """
        import asyncio

        offset = 0
        limit = 50  # Spotify's max per request

        while True:
            # Fetch a page of liked tracks (synchronous Spotipy → thread pool)
            results = await asyncio.to_thread(
                self._sp.current_user_saved_tracks,
                limit=limit,
                offset=offset,
            )

            items = results.get("items") or []
            if not items:
                break

            for item in items:
                track = item.get("track") or {}
                added_at_str = item.get("added_at", "")

                track_id = track.get("id", "")
                if not track_id:
                    continue

                artists = track.get("artists") or [{}]
                primary_artist = artists[0].get("name", "Unknown Artist")

                album = track.get("album") or {}
                album_name = album.get("name", "")

                external_urls = track.get("external_urls") or {}
                spotify_url = external_urls.get("spotify", "")

                yield GatewayItem(
                    import_ref=f"spotify:liked:{track_id}",
                    slug=f"spotify-liked-{track_id}",
                    title=f"{track.get('name', '')} — {primary_artist}",
                    body={
                        "track_name": track.get("name", ""),
                        "artist_name": primary_artist,
                        "album_name": album_name,
                        "spotify_url": spotify_url,
                        "liked_at": added_at_str,
                    },
                )

            # Check if there are more pages
            if not results.get("next"):
                break
            offset += limit
