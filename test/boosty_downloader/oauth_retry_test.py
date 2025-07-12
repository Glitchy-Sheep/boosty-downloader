"""Test OAuth retry functionality for inaccessible posts"""

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


class TestOAuthRetryFunctionality:
    """Test OAuth retry functionality for inaccessible posts"""

    @pytest.fixture
    def mock_post(self):
        """Create a mock post that is initially inaccessible"""
        post = Post(
            id='test-post-id',
            title='Test Post',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            has_access=False,
            data=[],
            signed_query='',
        )
        return post

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
    def mock_oauth_client(self):
        """Create a mock OAuth client"""
        client = AsyncMock()
        client.force_refresh_tokens = AsyncMock()
        client.get_author_posts = AsyncMock()
        return client

    @pytest.fixture
    def mock_non_oauth_client(self):
        """Create a mock non-OAuth client (without force_refresh_tokens)"""
        client = AsyncMock()
        # Don't add force_refresh_tokens to simulate non-OAuth client
        return client

    @pytest.fixture
    def download_manager(self, tmp_path, mock_oauth_client):
        """Create a download manager with mocked dependencies"""
        general_options = GeneralOptions(
            target_directory=tmp_path,
            request_delay_seconds=0,
            download_content_type_filters=[],
            preferred_video_quality=VideoQualityOption.medium,
            oauth_refresh_cooldown=3600,
        )
        logger_deps = MagicMock()
        logger_deps.logger = MagicMock()
        logger_deps.failed_downloads_logger = MagicMock()

        network_deps = MagicMock()
        network_deps.api_client = mock_oauth_client

        manager = BoostyDownloadManager(
            general_options=general_options,
            logger_dependencies=logger_deps,
            network_dependencies=network_deps,
        )
        manager._post_cache = MagicMock()
        return manager

    @pytest.mark.anyio
    async def test_non_oauth_client_skips_immediately(
        self, tmp_path, mock_non_oauth_client,
    ):
        """Test that non-OAuth clients skip inaccessible posts immediately"""
        # Setup
        general_options = GeneralOptions(
            target_directory=tmp_path,
            request_delay_seconds=0,
            download_content_type_filters=[],
            preferred_video_quality=VideoQualityOption.medium,
            oauth_refresh_cooldown=3600,
        )
        logger_deps = MagicMock()
        logger_deps.logger = MagicMock()
        logger_deps.failed_downloads_logger = MagicMock()

        network_deps = MagicMock()
        network_deps.api_client = mock_non_oauth_client

        manager = BoostyDownloadManager(
            general_options=general_options,
            logger_dependencies=logger_deps,
            network_dependencies=network_deps,
        )
        manager._post_cache = MagicMock()

        post = Post(
            id='test-post-id',
            title='Test Post',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            has_access=False,
            data=[],
            signed_query='',
        )

        post_location = PostLocation(
            title='Test Post',
            full_name='2023-01-01 - Test Post',
            username='testuser',
            post_directory=tmp_path / 'testuser' / '2023-01-01 - Test Post',
        )

        stats = {'inaccessible': 0}

        # Execute
        should_skip = await manager._handle_inaccessible_post_with_retry(
            username='testuser',
            post=post,
            post_location_info=post_location,
            stats=stats,
        )

        # Verify
        assert should_skip is True
        assert stats['inaccessible'] == 1
        # Verify that logging was called for inaccessible post
        logger_deps.logger.warning.assert_called()
        warning_calls = [
            call
            for call in logger_deps.logger.warning.call_args_list
            if 'not accessible' in str(call)
        ]
        assert len(warning_calls) > 0

    @pytest.mark.anyio
    async def test_oauth_token_refresh_fails(
        self, download_manager, mock_post, mock_post_location,
    ):
        """Test behavior when OAuth token refresh fails"""
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
        download_manager._network_dependencies.api_client.force_refresh_tokens.assert_called_once()
        # Verify that logging was called for inaccessible post
        download_manager.logger.warning.assert_called()

    @pytest.mark.anyio
    async def test_oauth_token_refresh_succeeds_but_post_still_inaccessible(
        self, download_manager, mock_post, mock_post_location,
    ):
        """Test behavior when OAuth token refresh succeeds but post is still inaccessible"""
        # Setup
        download_manager._network_dependencies.api_client.force_refresh_tokens.return_value = True

        # Mock the API response with the post still inaccessible
        from boosty_downloader.src.boosty_api.models.post.extra import Extra
        from boosty_downloader.src.boosty_api.models.post.posts_request import (
            PostsResponse,
        )

        refreshed_post = Post(
            id='test-post-id',
            title='Test Post',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            has_access=False,  # Still no access
            data=[],
            signed_query='',
        )

        mock_response = PostsResponse(
            posts=[refreshed_post],
            extra=Extra(
                is_last=True,
                offset='',
            ),
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
        download_manager._network_dependencies.api_client.force_refresh_tokens.assert_called_once()
        download_manager._network_dependencies.api_client.get_author_posts.assert_called_once()
        # Verify that logging was called for inaccessible post
        download_manager.logger.warning.assert_called()

    @pytest.mark.anyio
    async def test_oauth_token_refresh_succeeds_and_post_becomes_accessible(
        self, download_manager, mock_post, mock_post_location,
    ):
        """Test behavior when OAuth token refresh succeeds and post becomes accessible"""
        # Setup
        download_manager._network_dependencies.api_client.force_refresh_tokens.return_value = True

        # Mock the API response with the post now accessible
        from boosty_downloader.src.boosty_api.models.post.extra import Extra
        from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_text import (
            PostDataText,
        )
        from boosty_downloader.src.boosty_api.models.post.posts_request import (
            PostsResponse,
        )

        refreshed_post = Post(
            id='test-post-id',
            title='Test Post',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            has_access=True,  # Now has access!
            data=[
                PostDataText(
                    content='Now accessible content', type='text', modificator='',
                ),
            ],
            signed_query='?refreshed=true',
        )

        mock_response = PostsResponse(
            posts=[refreshed_post],
            extra=Extra(
                is_last=True,
                offset='',
            ),
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
        assert should_skip is False  # Should not skip, post is now accessible
        assert stats['inaccessible'] == 0  # Should not be counted as inaccessible

        # Verify the post object was updated
        assert mock_post.has_access is True
        assert mock_post.data == refreshed_post.data
        assert mock_post.signed_query == '?refreshed=true'

        download_manager._network_dependencies.api_client.force_refresh_tokens.assert_called_once()
        download_manager._network_dependencies.api_client.get_author_posts.assert_called_once()

    @pytest.mark.anyio
    async def test_oauth_api_error_during_retry(
        self, download_manager, mock_post, mock_post_location,
    ):
        """Test behavior when API error occurs during retry"""
        # Setup
        download_manager._network_dependencies.api_client.force_refresh_tokens.return_value = True
        download_manager._network_dependencies.api_client.get_author_posts.side_effect = Exception(
            'API Error',
        )
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
        download_manager._network_dependencies.api_client.force_refresh_tokens.assert_called_once()
        download_manager._network_dependencies.api_client.get_author_posts.assert_called_once()
        # Verify that error logging was called
        download_manager.logger.error.assert_called()

    @pytest.mark.anyio
    async def test_log_inaccessible_post_content(
        self, download_manager, mock_post, mock_post_location,
    ):
        """Test that inaccessible post information is properly logged"""
        # Execute
        await download_manager._log_inaccessible_post(
            post=mock_post,
            post_location_info=mock_post_location,
            username='testuser',
        )

        # Verify that warning and info logging was called
        download_manager.logger.warning.assert_called()
        download_manager.logger.info.assert_called()

        # Check that cache was NOT updated (inaccessible posts should not be cached)
        download_manager._post_cache.add_post_cache.assert_not_called()


if __name__ == '__main__':
    pytest.main([__file__])
