"""
The module contains a model for boosty 'post' data.

Only essentials fields defined for parsing purposes.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator, Field, TypeAdapter, ValidationError

from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataAudioDTO,
    BoostyPostDataExternalVideoDTO,
    BoostyPostDataFileDTO,
    BoostyPostDataHeaderDTO,
    BoostyPostDataImageDTO,
    BoostyPostDataLinkDTO,
    BoostyPostDataListDTO,
    BoostyPostDataOkVideoDTO,
    BoostyPostDataTextDTO,
    BoostyPostDataUnknownDTO,
)

KnownPostData = Annotated[
    BoostyPostDataTextDTO
    | BoostyPostDataAudioDTO
    | BoostyPostDataImageDTO
    | BoostyPostDataLinkDTO
    | BoostyPostDataFileDTO
    | BoostyPostDataExternalVideoDTO
    | BoostyPostDataOkVideoDTO
    | BoostyPostDataHeaderDTO
    | BoostyPostDataListDTO,
    Field(
        discriminator='type',
    ),
]

_KNOWN_POST_DATA = TypeAdapter[KnownPostData](KnownPostData)

# Error kinds meaning "the type tag itself is unknown or absent",
# as opposed to a known chunk arriving with a broken body.
_UNKNOWN_TAG_ERRORS = frozenset({'union_tag_invalid', 'union_tag_not_found'})


def _chunk_or_unknown(value: object) -> object:
    """
    Parse a post data chunk by its type tag.

    A chunk with an unknown tag becomes BoostyPostDataUnknownDTO.
    A known chunk with a broken body stays a validation error:
    masking it as unknown would silently drop real content.
    """
    try:
        return _KNOWN_POST_DATA.validate_python(value)
    except ValidationError as e:
        if all(err['type'] in _UNKNOWN_TAG_ERRORS for err in e.errors()):
            return BoostyPostDataUnknownDTO.model_validate(value)
        raise


BasePostData = Annotated[
    KnownPostData | BoostyPostDataUnknownDTO,
    BeforeValidator(_chunk_or_unknown),
]
