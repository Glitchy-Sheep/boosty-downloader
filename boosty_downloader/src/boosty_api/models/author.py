"""Represents an author of posts with all their content."""

from pydantic import BaseModel

from boosty_downloader.src.boosty_api.models.post.post import Post


class Author(BaseModel):
    """Represents an author of posts with all their content."""

    name: str
    url: str
    posts: list[Post]
