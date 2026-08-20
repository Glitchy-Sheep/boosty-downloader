"""Fallback model for post data chunks of types this client doesn't know yet."""

from boosty_downloader.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataUnknownDTO(BoostyBaseDTO):
    """
    Post data chunk of a type this client doesn't know yet.

    Boosty adds new content types over time. Such chunks parse into this
    fallback, get skipped by the mapper and are reported in the run summary.
    """

    type: str = 'unknown'
