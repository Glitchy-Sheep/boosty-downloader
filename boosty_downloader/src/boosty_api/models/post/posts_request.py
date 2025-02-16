"""Models for posts responses to boosty.to"""

from pydantic import BaseModel

from boosty_downloader.src.boosty_api.models.post.extra import Extra
from boosty_downloader.src.boosty_api.models.post.post import Post


class PostsResponse(BaseModel):
    """Model representing a response from a posts request"""

    posts: list[Post]
    extra: Extra
