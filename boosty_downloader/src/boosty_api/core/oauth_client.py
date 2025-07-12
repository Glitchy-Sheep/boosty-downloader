"""OAuth-enhanced Boosty API client with automatic token refresh"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from boosty_downloader.src.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.src.loggers.logger_instances import downloader_logger

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from aiohttp_retry import RetryClient

    from boosty_downloader.src.boosty_api.models.post.posts_request import PostsResponse
    from boosty_downloader.src.boosty_api.utils.oauth_manager import OAuthManager


class OAuthBoostyAPIClient(BoostyAPIClient):
    """
    OAuth-enhanced Boosty API client with automatic token refresh.

    Falls back to regular behavior if OAuth is not available.
    """

    def __init__(self, session: RetryClient, oauth_manager: OAuthManager | None = None) -> None:
        super().__init__(session)
        self.oauth_manager = oauth_manager

    async def get_author_posts(
        self,
        author_name: str,
        limit: int,
        offset: str | None = None,
    ) -> PostsResponse:
        """Request to get posts from the specified author with OAuth token refresh."""
        # Try to refresh OAuth tokens if available
        if self.oauth_manager:
            refreshed = await self.oauth_manager.refresh_if_needed(self.session)
            if refreshed:
                downloader_logger.info('OAuth tokens refreshed before API request')

        # Make the request (parent class handles the actual API call)
        return await super().get_author_posts(author_name, limit, offset)

    async def iterate_over_posts(
        self,
        author_name: str,
        delay_seconds: float = 0,
        posts_per_page: int = 5,
    ) -> AsyncGenerator[PostsResponse, None]:
        """Infinite generator iterating over posts with OAuth token refresh."""
        offset = None
        while True:
            await asyncio.sleep(delay_seconds)

            # Check and refresh OAuth tokens if needed
            if self.oauth_manager:
                refreshed = await self.oauth_manager.refresh_if_needed(self.session)
                if refreshed:
                    downloader_logger.info('OAuth tokens refreshed during iteration')

            response = await self.get_author_posts(
                author_name,
                offset=offset,
                limit=posts_per_page,
            )
            yield response
            if response.extra.is_last:
                break
            offset = response.extra.offset
