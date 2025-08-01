"""Module define the Post domain model for further downloading."""

from datetime import datetime

from boosty_downloader.src.domain.post_data_chunks import (
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
    PostDataChunkText,
    PostDataChunkTextualList,
)


class Post:
    """Post on boosty.to which have different kinds of content (images, text, videos, etc.)"""

    title: str
    created_at: datetime
    updated_at: datetime
    has_access: bool

    signed_query: str

    posts_data_chunks: list[
        PostDataChunkImage
        | PostDataChunkText
        | PostDataChunkBoostyVideo
        | PostDataChunkExternalVideo
        | PostDataChunkFile
        | PostDataChunkTextualList
    ]
