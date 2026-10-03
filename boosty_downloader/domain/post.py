"""Module define the Post domain model for further downloading."""

from dataclasses import dataclass, field
from datetime import datetime

from boosty_downloader.domain.post_data_chunks import (
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


@dataclass
class SubscriptionLevel:
    """The subscription tier that unlocks a post."""

    name: str
    # In the account's display currency.
    price: float
    # The same price in every currency; carries the stable RUB value.
    currency_prices: dict[str, float] | None = None


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

    published_at: datetime | None = None
    tags: list[str] = field(default_factory=list[str])
    # The pictures shown in place of the post when the account cannot open it.
    teaser: list[PostDataChunkImage] = field(default_factory=list[PostDataChunkImage])
    # Pieces by the API's kind, such as {'ok_video': 5, 'file': 5}, also for a locked post.
    content_counters: dict[str, int] = field(default_factory=dict[str, int])
    likes: int = 0
    comments: int = 0
    # How the post is unlocked: its tier, and its price when sold one by one (0 otherwise).
    subscription_level: SubscriptionLevel | None = None
    price: float = 0
    currency_prices: dict[str, float] | None = None
