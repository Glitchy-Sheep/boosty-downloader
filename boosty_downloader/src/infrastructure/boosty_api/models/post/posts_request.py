"""Models for posts responses to boosty.to"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_core import ErrorDetails

    from boosty_downloader.src.infrastructure.boosty_api.models.post.extra import Extra
    from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO


@dataclass(frozen=True, slots=True)
class SkippedPost:
    """A post this client could not parse: identity plus raw validation details."""

    post_id: str
    title: str
    errors: list[ErrorDetails]


@dataclass
class PostsResponse:
    """One page of an author's posts, as parsed by the client."""

    posts: list[PostDTO]
    extra: Extra
    # Posts with structures this client doesn't understand. Raw details here;
    # rendering them for the user is the output layer's job.
    skipped_posts: list[SkippedPost] = field(default_factory=list[SkippedPost])
