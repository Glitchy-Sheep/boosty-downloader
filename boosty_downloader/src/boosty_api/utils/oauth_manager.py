"""OAuth manager for automatic token refresh"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import aiohttp
from pydantic import ValidationError

from boosty_downloader.src.boosty_api.models.oauth import (
    OAuthRefreshResponse,
    OAuthTokens,
)
from boosty_downloader.src.loggers.logger_instances import downloader_logger

# Constants
HTTP_OK = 200  # HTTP OK status code

if TYPE_CHECKING:
    from pathlib import Path

    from aiohttp_retry import RetryClient


class OAuthError(Exception):
    """Base class for OAuth-related errors"""


class OAuthRefreshError(OAuthError):
    """Raised when token refresh fails"""


class OAuthManager:
    """Manages OAuth tokens with automatic refresh"""

    def __init__(self, tokens_file: Path) -> None:
        self.tokens_file = tokens_file
        self._tokens: OAuthTokens | None = None
        self._load_tokens()

    def _load_tokens(self) -> None:
        """Load tokens from file"""
        if not self.tokens_file.exists():
            return

        try:
            with self.tokens_file.open() as f:
                data = json.load(f)
                self._tokens = OAuthTokens.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            downloader_logger.warning(f'Failed to load OAuth tokens: {e}')

    def _save_tokens(self) -> None:
        """Save tokens to file"""
        if self._tokens is None:
            return

        try:
            self.tokens_file.parent.mkdir(parents=True, exist_ok=True)
            with self.tokens_file.open('w') as f:
                json.dump(self._tokens.model_dump(), f, indent=2)
        except OSError as e:
            downloader_logger.warning(f'Failed to save OAuth tokens: {e}')

    def has_tokens(self) -> bool:
        """Check if OAuth tokens are available"""
        return self._tokens is not None

    def get_access_token(self) -> str:
        """Get current access token"""
        if self._tokens is None:
            msg = 'No OAuth tokens available'
            raise OAuthError(msg)
        return self._tokens.access_token

    def is_expired(self) -> bool:
        """Check if access token is expired"""
        if self._tokens is None:
            return True
        return self._tokens.is_expired()

    async def refresh_if_needed(self, session: RetryClient) -> bool:
        """Refresh tokens if needed. Returns True if refreshed"""
        if not self.has_tokens() or not self.is_expired():
            return False

        try:
            await self._refresh_tokens(session)
            return True
        except OAuthRefreshError:
            return False

    async def _refresh_tokens(self, session: RetryClient) -> None:
        """Refresh OAuth tokens"""
        if self._tokens is None:
            msg = 'No tokens to refresh'
            raise OAuthRefreshError(msg)

        form_data = {
            'device_id': self._tokens.device_id,
            'device_os': 'web',
            'grant_type': 'refresh_token',
            'refresh_token': self._tokens.refresh_token,
        }

        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Authorization': f'Bearer {self._tokens.access_token}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
        }

        try:
            async with session.post(
                '/oauth/token/',
                data=form_data,
                headers=headers,
            ) as resp:
                if resp.status != HTTP_OK:
                    msg = f'Token refresh failed with status {resp.status}'
                    raise OAuthRefreshError(msg)

                data = await resp.json()
                refresh_response = OAuthRefreshResponse.model_validate(data)

                # Update tokens
                self._tokens = OAuthTokens(
                    access_token=refresh_response.access_token,
                    refresh_token=refresh_response.refresh_token,
                    expires_at=int(datetime.now(timezone.utc).timestamp()) + refresh_response.expires_in,
                    device_id=self._tokens.device_id,
                )

                self._save_tokens()
                downloader_logger.info('OAuth tokens refreshed successfully')

        except (aiohttp.ClientError, ValidationError) as e:
            msg = f'Token refresh failed: {e}'
            raise OAuthRefreshError(msg) from e

    def set_tokens(self, tokens: OAuthTokens) -> None:
        """Set new OAuth tokens"""
        self._tokens = tokens
        self._save_tokens()
        downloader_logger.info('OAuth tokens updated')
