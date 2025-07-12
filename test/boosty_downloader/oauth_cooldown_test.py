"""Test OAuth retry cooldown functionality"""

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from boosty_downloader.src.boosty_api.models.post.post import Post
from boosty_downloader.src.download_manager.download_manager import (
    BoostyDownloadManager,
    PostLocation,
)
from boosty_downloader.src.download_manager.download_manager_config import (
    GeneralOptions,
    VideoQualityOption,
)


class TestOAuthCooldownFunctionality:
    """Test OAuth retry cooldown functionality to prevent excessive token refresh attempts"""

    @pytest.fixture
    def mock_post(self):
        """Create a mock post that is initially inaccessible"""
        return Post(
            id='test-post-id',
            title='Test Post',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            has_access=False,
            data=[],
            signed_query='',
        )

    @pytest.fixture
    def mock_post_location(self, tmp_path):
        """Create a mock post location"""
        return PostLocation(
            title='Test Post',
            full_name='2023-01-01 - Test Post',
            username='testuser',
            post_directory=tmp_path / 'testuser' / '2023-01-01 - Test Post',
        )

    @pytest.fixture
    def download_manager(self, tmp_path):
        """Create a download manager with mocked OAuth client"""
        general_options = GeneralOptions(
            target_directory=tmp_path,
            request_delay_seconds=0,
            download_content_type_filters=[],
            preferred_video_quality=VideoQualityOption.medium,
            oauth_refresh_cooldown=2,  # Use shorter cooldown for tests
        )

        logger_deps = MagicMock()
        logger_deps.logger = MagicMock()
        logger_deps.failed_downloads_logger = MagicMock()

        # Mock OAuth client
        mock_oauth_client = AsyncMock()
        mock_oauth_client.force_refresh_tokens = AsyncMock()
        mock_oauth_client.get_author_posts = AsyncMock()

        network_deps = MagicMock()
        network_deps.api_client = mock_oauth_client

        manager = BoostyDownloadManager(
            general_options=general_options,
            logger_dependencies=logger_deps,
            network_dependencies=network_deps,
        )
        manager._post_cache = MagicMock()

        # Set a shorter limit for testing
        manager._max_consecutive_refresh_attempts = 2  # Shorter limit for testing

        return manager

    @pytest.mark.anyio
    async def test_first_token_refresh_attempt_allowed(
        self, download_manager, mock_post, mock_post_location,
    ):
        """Test that the first token refresh attempt is allowed"""
        # Setup
        download_manager._network_dependencies.api_client.force_refresh_tokens.return_value = False
        stats = {'inaccessible': 0}

        # Execute
        should_skip = await download_manager._handle_inaccessible_post_with_retry(
            username='testuser',
            post=mock_post,
            post_location_info=mock_post_location,
            stats=stats,
        )

        # Verify
        assert should_skip is True
        assert stats['inaccessible'] == 1
        assert download_manager._consecutive_failed_refresh_count == 1
        assert download_manager._last_token_refresh_time is not None
        download_manager._network_dependencies.api_client.force_refresh_tokens.assert_called_once()

    @pytest.mark.anyio
    async def test_cooldown_blocks_rapid_refresh_attempts(
        self, download_manager, mock_post, mock_post_location,
    ):
        """Test that cooldown prevents rapid consecutive refresh attempts"""
        # Setup - simulate a recent refresh attempt
        download_manager._last_token_refresh_time = time.time()
        download_manager._consecutive_failed_refresh_count = 0
        stats = {'inaccessible': 0}

        # Execute
        should_skip = await download_manager._handle_inaccessible_post_with_retry(
            username='testuser',
            post=mock_post,
            post_location_info=mock_post_location,
            stats=stats,
        )

        # Verify
        assert should_skip is True
        assert stats['inaccessible'] == 1
        # Token refresh should NOT be called due to cooldown
        download_manager._network_dependencies.api_client.force_refresh_tokens.assert_not_called()

    @pytest.mark.anyio
    async def test_cooldown_allows_refresh_after_timeout(
        self, download_manager, mock_post, mock_post_location,
    ):
        """Test that refresh is allowed after cooldown period expires"""
        # Setup - simulate an old refresh attempt
        download_manager._last_token_refresh_time = time.time() - 5  # 5 seconds ago
        download_manager._consecutive_failed_refresh_count = 0
        download_manager._network_dependencies.api_client.force_refresh_tokens.return_value = False
        stats = {'inaccessible': 0}

        # Execute
        should_skip = await download_manager._handle_inaccessible_post_with_retry(
            username='testuser',
            post=mock_post,
            post_location_info=mock_post_location,
            stats=stats,
        )

        # Verify
        assert should_skip is True
        assert stats['inaccessible'] == 1
        # Token refresh should be called after cooldown expired
        download_manager._network_dependencies.api_client.force_refresh_tokens.assert_called_once()

    @pytest.mark.anyio
    async def test_consecutive_failures_block_further_attempts(
        self, download_manager, mock_post, mock_post_location,
    ):
        """Test that too many consecutive failures block further refresh attempts"""
        # Setup - simulate max consecutive failures reached
        download_manager._consecutive_failed_refresh_count = 2  # At max limit
        download_manager._last_token_refresh_time = None  # No cooldown
        stats = {'inaccessible': 0}

        # Execute
        should_skip = await download_manager._handle_inaccessible_post_with_retry(
            username='testuser',
            post=mock_post,
            post_location_info=mock_post_location,
            stats=stats,
        )

        # Verify
        assert should_skip is True
        assert stats['inaccessible'] == 1
        # Token refresh should NOT be called due to too many failures
        download_manager._network_dependencies.api_client.force_refresh_tokens.assert_not_called()

    @pytest.mark.anyio
    async def test_successful_refresh_resets_failure_count(
        self, download_manager, mock_post, mock_post_location,
    ):
        """Test that successful token refresh resets the consecutive failure count"""
        # Setup
        download_manager._consecutive_failed_refresh_count = 1  # Some failures
        download_manager._last_token_refresh_time = None  # No cooldown
        download_manager._network_dependencies.api_client.force_refresh_tokens.return_value = True

        # Mock successful API response that still shows post as inaccessible
        from boosty_downloader.src.boosty_api.models.post.extra import Extra
        from boosty_downloader.src.boosty_api.models.post.posts_request import (
            PostsResponse,
        )

        still_inaccessible_post = Post(
            id='test-post-id',
            title='Test Post',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            has_access=False,
            data=[],
            signed_query='',
        )

        mock_response = PostsResponse(
            posts=[still_inaccessible_post],
            extra=Extra(is_last=True, offset=''),
        )

        download_manager._network_dependencies.api_client.get_author_posts.return_value = mock_response
        stats = {'inaccessible': 0}

        # Execute
        should_skip = await download_manager._handle_inaccessible_post_with_retry(
            username='testuser',
            post=mock_post,
            post_location_info=mock_post_location,
            stats=stats,
        )

        # Verify
        assert should_skip is True
        assert stats['inaccessible'] == 1
        # Consecutive failure count should be reset after successful refresh
        assert download_manager._consecutive_failed_refresh_count == 0
        download_manager._network_dependencies.api_client.force_refresh_tokens.assert_called_once()

    @pytest.mark.anyio
    async def test_reset_oauth_retry_state(
        self, download_manager, mock_post, mock_post_location,
    ):
        """Test that reset_oauth_retry_state clears cooldown and failure count"""
        # Setup - simulate some failures and recent refresh
        download_manager._consecutive_failed_refresh_count = 2
        download_manager._last_token_refresh_time = time.time()
        download_manager._network_dependencies.api_client.force_refresh_tokens.return_value = False

        # Reset state
        download_manager.reset_oauth_retry_state()

        # Verify state is cleared
        assert download_manager._consecutive_failed_refresh_count == 0
        assert download_manager._last_token_refresh_time is None

        # Now a refresh attempt should be allowed
        stats = {'inaccessible': 0}
        should_skip = await download_manager._handle_inaccessible_post_with_retry(
            username='testuser',
            post=mock_post,
            post_location_info=mock_post_location,
            stats=stats,
        )

        # Verify refresh was attempted
        assert should_skip is True
        download_manager._network_dependencies.api_client.force_refresh_tokens.assert_called_once()

    @pytest.mark.anyio
    async def test_cooldown_state_persists_across_multiple_posts(
        self, download_manager, tmp_path,
    ):
        """Test that cooldown state is maintained across multiple inaccessible posts"""
        # Setup two different posts
        post1 = Post(
            id='post-1',
            title='Post 1',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            has_access=False,
            data=[],
            signed_query='',
        )

        post2 = Post(
            id='post-2',
            title='Post 2',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            has_access=False,
            data=[],
            signed_query='',
        )

        location1 = PostLocation(
            title='Post 1',
            full_name='2023-01-01 - Post 1',
            username='testuser',
            post_directory=tmp_path / 'testuser' / '2023-01-01 - Post 1',
        )

        location2 = PostLocation(
            title='Post 2',
            full_name='2023-01-02 - Post 2',
            username='testuser',
            post_directory=tmp_path / 'testuser' / '2023-01-02 - Post 2',
        )

        download_manager._network_dependencies.api_client.force_refresh_tokens.return_value = False
        stats = {'inaccessible': 0}

        # Process first post - should attempt refresh
        await download_manager._handle_inaccessible_post_with_retry(
            username='testuser',
            post=post1,
            post_location_info=location1,
            stats=stats,
        )

        # Verify first attempt was made
        assert (
            download_manager._network_dependencies.api_client.force_refresh_tokens.call_count
            == 1
        )
        assert download_manager._consecutive_failed_refresh_count == 1

        # Process second post immediately - should be blocked by cooldown
        await download_manager._handle_inaccessible_post_with_retry(
            username='testuser',
            post=post2,
            post_location_info=location2,
            stats=stats,
        )

        # Verify second attempt was blocked
        assert (
            download_manager._network_dependencies.api_client.force_refresh_tokens.call_count
            == 1
        )  # Still 1
        assert stats['inaccessible'] == 2


if __name__ == '__main__':
    pytest.main([__file__])
