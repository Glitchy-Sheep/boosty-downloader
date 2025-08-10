"""
The module contains a model for boosty 'post' data.

Only essentials fields defined for parsing purposes.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataExternalVideoDTO,
    BoostyPostDataFileDTO,
    BoostyPostDataHeaderDTO,
    BoostyPostDataImageDTO,
    BoostyPostDataLinkDTO,
    BoostyPostDataListDTO,
    BoostyPostDataOkVideoDTO,
    BoostyPostDataTextDTO,
)

BasePostData = Annotated[
    BoostyPostDataTextDTO
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
