"""
What the listing tells about a post besides its content.

Tags, counters by kind and reader activity. The post reads them tolerantly:
a missing or malformed value never fails it.
"""

from boosty_downloader.infrastructure.boosty_api.models.base import BoostyBaseDTO


class PostTagDTO(BoostyBaseDTO):
    """A tag the author put on the post."""

    title: str


class ContentCounterDTO(BoostyBaseDTO):
    """How many pieces of one kind the post holds, also when it is locked."""

    type: str
    count: int


class PostCountDTO(BoostyBaseDTO):
    """Reader activity on the post."""

    likes: int = 0
    comments: int = 0
