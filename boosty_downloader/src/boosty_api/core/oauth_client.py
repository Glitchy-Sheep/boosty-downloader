"""OAuth-enhanced Boosty API client with automatic token refresh"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from boosty_downloader.src.boosty_api.core.auth_validator import AuthValidator
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

    def __init__(
        self, session: RetryClient, oauth_manager: OAuthManager | None = None,
    ) -> None:
        super().__init__(session)
        self.oauth_manager = oauth_manager
        self.auth_validator = AuthValidator()

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
        response = await super().get_author_posts(author_name, limit, offset)

        # Add response to auth validator for analysis
        self.auth_validator.add_response(response)

        # Check for authentication issues periodically
        if (
            self.auth_validator._total_posts_checked > 0
            and self.auth_validator._total_posts_checked % 20 == 0
        ):
            auth_result = self.auth_validator.validate_auth_status()
            if not auth_result.is_valid:
                auth_result.log_issue()

                # Log statistics for debugging
                stats = self.auth_validator.get_statistics()
                downloader_logger.debug(f'Auth validation stats: {stats}')

        return response

    async def iterate_over_posts(
        self,
        author_name: str,
        delay_seconds: float = 0,
        posts_per_page: int = 5,
    ) -> AsyncGenerator[PostsResponse, None]:
        """Infinite generator iterating over posts with OAuth token refresh."""
        offset = None
        iteration_count = 0

        while True:
            await asyncio.sleep(delay_seconds)
            iteration_count += 1

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

            # Validate authentication status every 5 iterations
            if iteration_count % 5 == 0:
                auth_result = self.auth_validator.validate_auth_status()
                if not auth_result.is_valid:
                    auth_result.log_issue()

                    # For critical auth issues, consider stopping or warning
                    if auth_result.issue_type in [
                        'consecutive_empty_responses',
                        'no_access_to_posts',
                    ]:
                        downloader_logger.warning(
                            f'Critical authentication issue detected: {auth_result.issue_type}. '
                            'Consider checking your authentication setup.',
                        )

            yield response
            if response.extra.is_last:
                break
            offset = response.extra.offset

    def get_auth_statistics(self) -> dict[str, int | float]:
        """Get current authentication validation statistics"""
        return self.auth_validator.get_statistics()

    def reset_auth_validation(self) -> None:
        """Reset authentication validation statistics"""
        self.auth_validator.reset()
        downloader_logger.debug('Authentication validation statistics reset')

    async def force_refresh_tokens(self) -> bool:
        """Force refresh OAuth tokens regardless of expiry. Returns True if refreshed"""
        if not self.oauth_manager:
            return False

        refreshed = await self.oauth_manager.force_refresh(self.session)
        if refreshed:
            downloader_logger.info('OAuth tokens force refreshed')
        return refreshed
