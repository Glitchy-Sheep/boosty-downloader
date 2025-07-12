"""Tests for OAuth functionality"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from boosty_downloader.src.boosty_api.models.oauth import OAuthTokens
from boosty_downloader.src.boosty_api.utils.oauth_manager import OAuthManager


class TestOAuthManager(unittest.TestCase):
    """Test OAuth manager functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.tokens_file = self.temp_dir / 'oauth_tokens.json'
        self.oauth_manager = OAuthManager(self.tokens_file)

        # Sample OAuth tokens
        self.sample_tokens = OAuthTokens(
            access_token='test_access_token_123',
            refresh_token='test_refresh_token_456',
            expires_at=int(datetime.now(timezone.utc).timestamp()) + 3600,  # 1 hour from now
            device_id='test_device_id_789',
        )

    def tearDown(self):
        """Clean up test fixtures"""
        if self.tokens_file.exists():
            self.tokens_file.unlink()
        self.temp_dir.rmdir()

    def test_no_tokens_initially(self):
        """Test that manager has no tokens initially"""
        assert not self.oauth_manager.has_tokens()
        assert self.oauth_manager.is_expired()

    def test_set_and_get_tokens(self):
        """Test setting and getting OAuth tokens"""
        self.oauth_manager.set_tokens(self.sample_tokens)

        assert self.oauth_manager.has_tokens()
        assert not self.oauth_manager.is_expired()
        assert self.oauth_manager.get_access_token() == self.sample_tokens.access_token

    def test_save_and_load_tokens(self):
        """Test saving and loading tokens from file"""
        self.oauth_manager.set_tokens(self.sample_tokens)

        # Create new manager instance to test loading
        new_manager = OAuthManager(self.tokens_file)

        assert new_manager.has_tokens()
        assert new_manager.get_access_token() == self.sample_tokens.access_token

    def test_expired_tokens(self):
        """Test detection of expired tokens"""
        expired_tokens = OAuthTokens(
            access_token='expired_access_token',
            refresh_token='expired_refresh_token',
            expires_at=int(datetime.now(timezone.utc).timestamp()) - 3600,  # 1 hour ago
            device_id='expired_device_id',
        )

        self.oauth_manager.set_tokens(expired_tokens)

        assert self.oauth_manager.has_tokens()
        assert self.oauth_manager.is_expired()

    def test_file_persistence(self):
        """Test that tokens are properly saved to file"""
        self.oauth_manager.set_tokens(self.sample_tokens)

        # Check that file exists and contains correct data
        assert self.tokens_file.exists()

        with self.tokens_file.open() as f:
            data = json.load(f)

        assert data['access_token'] == self.sample_tokens.access_token
        assert data['refresh_token'] == self.sample_tokens.refresh_token
        assert data['device_id'] == self.sample_tokens.device_id


if __name__ == '__main__':
    unittest.main()
