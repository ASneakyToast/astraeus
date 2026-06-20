"""
Block definition for iNaturalist observation outings.

An "outing" is a single wildlife observation logged via the iNaturalist app.
Each observation becomes one CMS document of type ``inaturalist_observation``.

Register this block in your application::

    from examples.inaturalist_outings.blocks import INaturalistObservationBlock
    cms.register_block(INaturalistObservationBlock)
"""

from __future__ import annotations

from starlette_cms.fields import JSONField, NumberField, TextField, URLField
from starlette_cms.registry import block


@block("inaturalist_observation", append_only=True)
class INaturalistObservationBlock:
    """
    A single iNaturalist observation.

    ``append_only=True`` — observations are immutable once synced.
    """

    species_guess: str = TextField(label="Species (as identified)")
    taxon_name: str = TextField(label="Scientific Name", required=False)
    common_name: str = TextField(label="Common Name", required=False)
    observed_on: str = TextField(label="Observed On (ISO 8601 date)")
    place_guess: str = TextField(label="Place", required=False)
    latitude: float = NumberField(label="Latitude", required=False)
    longitude: float = NumberField(label="Longitude", required=False)
    quality_grade: str = TextField(label="Quality Grade", required=False)
    inaturalist_url: str = URLField(label="iNaturalist URL")
    photo_urls: list = JSONField(label="Photo URLs", default=[])  # type: ignore[assignment]
