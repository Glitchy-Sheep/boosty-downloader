"""Module define the Post domain model for further downloading."""

from dataclasses import dataclass
from datetime import datetime

from boosty_downloader.src.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
    PostDataChunkText,
    PostDataChunkTextualList,
)

PostDataAllChunks = (
    PostDataChunkImage
    | PostDataChunkText
    | PostDataChunkBoostyVideo
    | PostDataChunkExternalVideo
    | PostDataChunkFile
    | PostDataChunkTextualList
    | PostDataChunkAudio
)

PostDataAllChunksList = list[PostDataAllChunks]

PostDataPostOnlyChunksList = list[
    PostDataChunkText | PostDataChunkImage | PostDataChunkTextualList
]


@dataclass
class Post:
    """Post on boosty.to which have different kinds of content (images, text, videos, etc.)"""

    uuid: str
    title: str
    created_at: datetime
    updated_at: datetime
    has_access: bool

    signed_query: str

    post_data_chunks: PostDataAllChunksList
