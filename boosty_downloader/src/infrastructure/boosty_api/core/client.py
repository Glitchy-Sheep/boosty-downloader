"""Boosty API client for accessing content."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from aiolimiter import AsyncLimiter
from pydantic import ValidationError
from yarl import URL

from boosty_downloader.src.infrastructure.boosty_api.core.endpoints import (
    BOOSTY_DEFAULT_BASE_URL,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.extra import Extra
from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.src.infrastructure.boosty_api.models.post.posts_request import (
    PostsResponse,
)
from boosty_downloader.src.infrastructure.boosty_api.utils.filter_none_params import (
    filter_none_params,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping

    from aiohttp import ClientResponse
    from aiohttp_retry import RetryClient
    from pydantic_core import ErrorDetails


class BoostyAPIError(Exception):
    """Base class for all Boosty API related errors."""


class BoostyAPINoUsernameError(BoostyAPIError):
    """Raised when no username is specified."""

    username: str

    def __init__(self, username: str) -> None:
        super().__init__(f'Username not found: {username}')
        self.username = username


class BoostyAPIUnauthorizedError(BoostyAPIError):
    """Raised when authorization error occurs, e.g when credentials is invalid."""


class BoostyAPIUnknownError(BoostyAPIError):
    """Raised when Boosty returns unexpected error."""

    details: str

    def __init__(self, status_code: int, details: str) -> None:
        super().__init__(f'Boosty returned unknown error[{status_code}]: {details}')
        self.details = details


class BoostyAPIValidationError(BoostyAPIError):
    """
    Raised when validation error occurs, e.g. when response data is invalid.

    It can happen if the API response structure changes.
    In that case the client should be updated to match the new structure.
    """

    errors: list[ErrorDetails]

    def __init__(self, errors: list[ErrorDetails]) -> None:
        super().__init__('Boosty API response validation error')
        self.errors = errors


def _create_limiter(request_delay_seconds: float) -> AsyncLimiter | None:
    # aiolimiter expects max_rate and time_period to be positive.
    # For delays <1s, we use a 1-second window and scale the rate to avoid exceptions and ensure correct throttling.
    # For delays >=1s, we allow 1 request per delay period, matching the intended throttle.
    # Without this logic, certain values (e.g. delay=0.5) would cause aiolimiter to raise or throttle incorrectly.
    if request_delay_seconds > 0:
        if request_delay_seconds < 1:
            max_rate = 1 / request_delay_seconds
            time_period = 1
        else:
            max_rate = 1
            time_period = request_delay_seconds
        return AsyncLimiter(max_rate=max_rate, time_period=time_period)
    return None


class BoostyAPIClient:
    """
    Main client class for the Boosty API.

    The session you provide to this class MUST NOT CONTAIN BASE URL.
    It should only contain headers and cookies. Base url is set internally.

    It handles the connection and makes requests to the API.
    To work with private/paid posts you need to provide valid authentication token and cookies in the session.
    """

    def __init__(
        self,
        session: RetryClient,
        request_delay_seconds: float = 0.0,
        base_url: URL | None = None,
    ) -> None:
        self._base_url = base_url or BOOSTY_DEFAULT_BASE_URL
        self.session = session
        self._limiter = _create_limiter(request_delay_seconds)

    async def _throttled_get(
        self,
        endpoint: str,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> ClientResponse:
        url = URL(self._base_url) / endpoint.lstrip('/')

        if self._limiter:
            async with self._limiter:
                return await self.session.get(url, params=params, headers=headers)
        return await self.session.get(url, params=params, headers=headers)

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

        posts_raw = await self._throttled_get(
            endpoint,
            params=filter_none_params(
                {
                    'offset': offset,
                    'limit': limit,
                },
            ),
        )
        posts_data = await posts_raw.json()

        if posts_raw.status == HTTPStatus.NOT_FOUND:
            raise BoostyAPINoUsernameError(author_name)

        # This will be returned if the user has creds but they're invalid/expired
        if posts_raw.status == HTTPStatus.UNAUTHORIZED:
            raise BoostyAPIUnauthorizedError

        if posts_raw.status != HTTPStatus.OK:
            raise BoostyAPIUnknownError(
                posts_raw.status, f'Unexpected status code: {posts_raw.status}'
            )

        try:
            posts: list[PostDTO] = [
                PostDTO.model_validate(post) for post in posts_data['data']
            ]
            extra: Extra = Extra.model_validate(posts_data['extra'])
        except ValidationError as e:
            raise BoostyAPIValidationError(errors=e.errors()) from e

        return PostsResponse(
            posts=posts,
            extra=extra,
        )

    async def iterate_over_posts(
        self,
        author_name: str,
        posts_per_page: int = 5,
    ) -> AsyncGenerator[PostsResponse, None]:
        """
        Infinite generator iterating over posts of the specified author.

        The generator will yield all posts of the author, paginating internally.
        """
        offset = None
        while True:
            response = await self.get_author_posts(
                author_name,
                offset=offset,
                limit=posts_per_page,
            )
            yield response
            if response.extra.is_last:
                break
            offset = response.extra.offset
