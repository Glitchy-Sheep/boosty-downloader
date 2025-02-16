"""Boosty API client for accessing content."""

from __future__ import annotations

import aiohttp

from boosty_downloader.src.boosty_api.models.post.extra import Extra
from boosty_downloader.src.boosty_api.models.post.post import Post
from boosty_downloader.src.boosty_api.models.post.posts_request import PostsResponse
from boosty_downloader.src.boosty_api.utils.filter_none_params import filter_none_params


class BoostyAPIClient:
    """
    Main client class for the Boosty API.

    It handles the connection and makes requests to the API.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    async def get_author_posts(
        self,
        author_name: str,
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
                },
            ),
        )
        posts_data = await posts_raw.json()

        posts: list[Post] = [Post.model_validate(post) for post in posts_data['data']]
        extra: Extra = Extra.model_validate(posts_data['extra'])

        return PostsResponse(
            posts=posts,
            extra=extra,
        )
