"""
The module contains a model for boosty 'post' data.

Only essentials fields defined for parsing purposes.
"""

from __future__ import annotations

from typing import Annotated, Union

from pydantic import Field

from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_file import (
    PostDataFile,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_image import (
    PostDataImage,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_link import (
    PostDataLink,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_ok_video import (
    PostDataOkVideo,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_text import (
    PostDataText,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_video import (
    PostDataVideo,
)

BasePostData = Annotated[
    Union[
        PostDataText,
        PostDataImage,
        PostDataLink,
        PostDataFile,
        PostDataVideo,
        PostDataOkVideo,
    ],
    Field(
        discriminator='type',
    ),
]
