"""OAuth models for authentication data"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

# Constants
TOKEN_EXPIRY_BUFFER_SECONDS = 300  # 5 minutes buffer before token expiry


class OAuthTokens(BaseModel):
    """OAuth tokens for Boosty API authentication"""

    access_token: str = Field(..., min_length=1)
    refresh_token: str = Field(..., min_length=1)
    expires_at: int = Field(..., gt=0)
    device_id: str = Field(..., min_length=1)

    def is_expired(self) -> bool:
        """Check if access token is expired (with 5 minutes buffer)"""
        return datetime.now(timezone.utc).timestamp() >= (self.expires_at - TOKEN_EXPIRY_BUFFER_SECONDS)


class OAuthRefreshResponse(BaseModel):
    """Response from OAuth token refresh endpoint"""

    access_token: str
    refresh_token: str
    expires_in: int
