"""Models for posts responses to boosty.to"""

from typing import Any

from pydantic import BaseModel

from boosty_downloader.src.boosty_api.models.post.extra import Extra
from boosty_downloader.src.boosty_api.models.post.post import Post


class PostsResponse(BaseModel):
    """Model representing a response from a posts request"""

    posts: list[Post]
    extra: Extra
    raw_posts_data: list[dict[str, Any]] = []  # Raw API data for each post
