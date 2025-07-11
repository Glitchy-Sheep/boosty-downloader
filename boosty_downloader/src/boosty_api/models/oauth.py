"""OAuth models for authentication data"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class OAuthTokens(BaseModel):
    """OAuth tokens for Boosty API authentication"""
    
    access_token: str = Field(..., min_length=1)
    refresh_token: str = Field(..., min_length=1)
    expires_at: int = Field(..., gt=0)
    device_id: str = Field(..., min_length=1)
    
    def is_expired(self) -> bool:
        """Check if access token is expired (with 5 minutes buffer)"""
        return datetime.now().timestamp() >= (self.expires_at - 300)


class OAuthRefreshResponse(BaseModel):
    """Response from OAuth token refresh endpoint"""
    
    access_token: str
    refresh_token: str
    expires_in: int 