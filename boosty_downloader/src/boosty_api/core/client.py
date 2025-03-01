"""Boosty API client for accessing content."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from boosty_downloader.src.boosty_api.models.post.extra import Extra
from boosty_downloader.src.boosty_api.models.post.post import Post
from boosty_downloader.src.boosty_api.models.post.posts_request import PostsResponse
from boosty_downloader.src.boosty_api.utils.filter_none_params import filter_none_params

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from aiohttp_retry import RetryClient


class BoostyAPIError(Exception):
    """Base class for all Boosty API related errors."""


class BoostyAPINoUsernameError(BoostyAPIError):
    """Raised when no username is specified."""


class BoostyAPIClient:
    """
    Main client class for the Boosty API.

    It handles the connection and makes requests to the API.
    """

    def __init__(self, session: RetryClient) -> None:
        self.session = session

    async def get_author_posts(
        self,
        author_name: str,
        limit: int,
        offset: str | None = None,
    ) -> PostsResponse:
        """
        Request to get posts from the specified author.

        The request supports pagination, so the response contains meta info.
        If you want to get all posts, you need to repeat the request with the offset of previous response
        until the 'is_last' field becomes True.
        """
        endpoint = f'blog/{author_name}/post/'

        posts_raw = await self.session.get(
            endpoint,
            params=filter_none_params(
                {
                    'offset': offset,
                    'limit': limit,
                },
            ),
        )
        posts_data = await posts_raw.json()

        try:
            posts: list[Post] = [
                Post.model_validate(post) for post in posts_data['data']
            ]
        except KeyError as e:
            raise BoostyAPINoUsernameError from e

        extra: Extra = Extra.model_validate(posts_data['extra'])

        return PostsResponse(
            posts=posts,
            extra=extra,
        )

    async def iterate_over_posts(
        self,
        author_name: str,
        delay_seconds: float = 0,
        posts_per_page: int = 5,
    ) -> AsyncGenerator[PostsResponse, None]:
        """
        Infinite generator iterating over posts of the specified author.

        The generator will yield all posts of the author, paginating internally.
        """
        offset = None
        while True:
            await asyncio.sleep(delay_seconds)
            response = await self.get_author_posts(
                author_name,
                offset=offset,
                limit=posts_per_page,
            )
            yield response
            if response.extra.is_last:
                break
            offset = response.extra.offset
