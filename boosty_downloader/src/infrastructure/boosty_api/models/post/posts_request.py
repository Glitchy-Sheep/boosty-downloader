"""Models for posts responses to boosty.to"""

from pydantic import BaseModel

from boosty_downloader.src.infrastructure.boosty_api.models.post.extra import Extra
from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO


class PostsResponse(BaseModel):
    """Model representing a response from a posts request"""

    posts: list[PostDTO]
    extra: Extra
