"""Boosty API client for accessing content."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import aiohttp

from boosty_downloader.src.boosty_api.models.post.extra import Extra
from boosty_downloader.src.boosty_api.models.post.post import Post
from boosty_downloader.src.boosty_api.models.post.posts_request import PostsResponse
from boosty_downloader.src.boosty_api.utils.filter_none_params import filter_none_params
from boosty_downloader.src.loggers.logger_instances import downloader_logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from aiohttp_retry import RetryClient


class BoostyAPIError(Exception):
    """Base class for all Boosty API related errors."""


class BoostyAPINoUsernameError(BoostyAPIError):
    """Raised when no username is specified."""


class BoostyAPIAuthenticationError(BoostyAPIError):
    """Raised when authentication fails."""


class BoostyAPIUnauthorizedError(BoostyAPIError):
    """Raised when access is denied (401/403)."""


class BoostyAPIRateLimitError(BoostyAPIError):
    """Raised when rate limit is exceeded (429)."""


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

        try:
            posts_raw = await self.session.get(
                endpoint,
                params=filter_none_params(
                    {
                        'offset': offset,
                        'limit': limit,
                    },
                ),
            )
        except aiohttp.ClientResponseError as e:
            await self._handle_http_error(e, author_name)
            raise  # Re-raise after handling

        posts_data = await posts_raw.json()

        # Check for API-level errors (even with 200 status)
        if isinstance(posts_data, dict) and 'error' in posts_data:
            error_code = posts_data.get('error', 'unknown_error')
            error_description = posts_data.get('error_description', 'No description')

            if error_code == 'blog_not_found':
                raise BoostyAPINoUsernameError(
                    f"Blog '{author_name}' not found: {error_description}",
                )
            if error_code in ['unauthorized', 'access_denied', 'invalid_token']:
                raise BoostyAPIAuthenticationError(
                    f'Authentication error: {error_description}',
                )
            raise BoostyAPIError(f'API error: {error_code} - {error_description}')

        try:
            posts: list[Post] = [
                Post.model_validate(post) for post in posts_data['data']
            ]
        except KeyError as e:
            # Check if this is an authentication issue
            if 'data' not in posts_data:
                downloader_logger.warning(
                    f"No 'data' field in API response for {author_name}",
                )
                downloader_logger.debug(
                    f'Response keys: {list(posts_data.keys()) if isinstance(posts_data, dict) else "Not a dict"}',
                )

                # This might be an authentication issue, but we can't be sure
                # Let's return empty posts instead of raising an error
                posts = []
            else:
                raise BoostyAPINoUsernameError(
                    f'Invalid response structure for {author_name}',
                ) from e

        # Handle missing extra field gracefully
        if 'extra' in posts_data:
            extra: Extra = Extra.model_validate(posts_data['extra'])
        else:
            downloader_logger.warning(
                f"No 'extra' field in API response for {author_name}",
            )
            # Create a default extra indicating this is the last page
            extra = Extra(is_last=True, offset='')

        return PostsResponse(
            posts=posts,
            extra=extra,
        )

    async def _handle_http_error(
        self, error: aiohttp.ClientResponseError, author_name: str,
    ) -> None:
        """Handle HTTP errors and provide appropriate error types and messages"""
        status = error.status

        if status == 401:
            downloader_logger.error(
                f'Authentication failed for {author_name} (401 Unauthorized)',
            )
            downloader_logger.info(
                'This usually means your authentication tokens are invalid or expired',
            )
            raise BoostyAPIUnauthorizedError('Authentication required or token expired')
        if status == 403:
            downloader_logger.error(
                f'Access forbidden for {author_name} (403 Forbidden)',
            )
            downloader_logger.info(
                "This usually means you don't have permission to access this content",
            )
            raise BoostyAPIUnauthorizedError(
                'Access forbidden - insufficient permissions',
            )
        if status == 404:
            downloader_logger.error(f"Blog '{author_name}' not found (404 Not Found)")
            raise BoostyAPINoUsernameError(f"Blog '{author_name}' not found")
        if status == 429:
            downloader_logger.error(
                f'Rate limit exceeded for {author_name} (429 Too Many Requests)',
            )
            downloader_logger.info('Try increasing the delay between requests')
            raise BoostyAPIRateLimitError('Rate limit exceeded - too many requests')
        downloader_logger.error(
            f'HTTP error {status} for {author_name}: {error.message}',
        )
        raise BoostyAPIError(f'HTTP {status}: {error.message}')

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
