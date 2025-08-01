"""
The module contains a model for boosty 'post' data.

Only essentials fields defined for parsing purposes.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    PostDataFile,
    PostDataHeader,
    PostDataImage,
    PostDataLink,
    PostDataList,
    PostDataOkVideo,
    PostDataText,
    PostDataVideo,
)

BasePostData = Annotated[
    PostDataText
    | PostDataImage
    | PostDataLink
    | PostDataFile
    | PostDataVideo
    | PostDataOkVideo
    | PostDataHeader
    | PostDataList,
    Field(
        discriminator='type',
    ),
]
