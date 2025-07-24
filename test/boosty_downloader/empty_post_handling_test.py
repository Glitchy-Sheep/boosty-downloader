"""Tests for empty and inaccessible post handling."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import anyio

from boosty_downloader.src.boosty_api.models.post.post import Post
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_text import (
    PostDataText,
)
from boosty_downloader.src.download_manager.download_manager import (
    BoostyDownloadManager,
)
from boosty_downloader.src.download_manager.download_manager_config import (
    DownloadContentTypeFilter,
    GeneralOptions,
    LoggerDependencies,
    NetworkDependencies,
    VideoQualityOption,
)
from boosty_downloader.src.loggers.logger_instances import downloader_logger


class TestEmptyPostHandling:
    """Test cases for handling empty and inaccessible posts."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())

        # Create mock dependencies
        self.mock_session = AsyncMock()
        self.mock_api_client = AsyncMock()
        self.mock_external_downloader = MagicMock()
        self.mock_failed_logger = MagicMock()

        # Create download manager
        self.download_manager = BoostyDownloadManager(
            general_options=GeneralOptions(
                target_directory=self.temp_dir,
                download_content_type_filters=[DownloadContentTypeFilter.post_content],
                request_delay_seconds=0,
                preferred_video_quality=VideoQualityOption.medium,
                oauth_refresh_cooldown=3600,
                save_raw_json=False,
                save_raw_txt=False,
            ),
            logger_dependencies=LoggerDependencies(
                logger=downloader_logger,
                failed_downloads_logger=self.mock_failed_logger,
            ),
            network_dependencies=NetworkDependencies(
                session=self.mock_session,
                api_client=self.mock_api_client,
                external_videos_downloader=self.mock_external_downloader,
            ),
        )

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir)

    def create_mock_post(
        self,
        post_id: str,
        title: str = 'Test Post',
        has_access: bool = True,
        data: list = None,
    ) -> Post:
        """Create a mock post for testing."""
        if data is None:
            data = []

        return Post(
            id=post_id,
            title=title,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            has_access=has_access,
            signed_query='',
            data=data,
        )

    def test_empty_post_handling(self):
        """Test handling of posts with no content."""

        async def _test_empty_post_handling():
            # Create a post with no data
            empty_post = self.create_mock_post(
                post_id='empty_post_123',
                title='Empty Post',
                has_access=True,
                data=[],  # No content
            )

            # Download the post
            result = await self.download_manager._download_single_post(
                username='test_user',
                post=empty_post,
            )

            # Should return True (successful processing)
            assert result is True

            # Check that marker file was created
            post_dir = (
                self.temp_dir
                / 'test_user'
                / f'{empty_post.created_at.date()} - Empty Post'
            )
            marker_file = post_dir / 'EMPTY_POST_MARKER.txt'

            assert post_dir.exists()
            assert marker_file.exists()

            # Check marker file content
            content = marker_file.read_text(encoding='utf-8')
            assert 'empty_post_123' in content
            assert 'Empty Post' in content
            assert 'no downloadable content' in content
            assert 'removed by the author' in content

        anyio.run(_test_empty_post_handling)

    def test_inaccessible_post_handling(self):
        """Test handling of posts with hasAccess=False."""

        async def _test_inaccessible_post_handling():
            # Create a post with no access
            inaccessible_post = self.create_mock_post(
                post_id='inaccessible_post_123',
                title='Private Post',
                has_access=False,
                data=[],  # Simple empty data to avoid validation issues
            )

            # Simulate the download process for inaccessible post
            post_location_info = self.download_manager._generate_post_location(
                username='test_user',
                post=inaccessible_post,
            )

            # Test the logging function directly - should complete without errors
            await self.download_manager._log_inaccessible_post(
                post=inaccessible_post,
                post_location_info=post_location_info,
                username='test_user',
            )

            # If we get here without exceptions, the test passes
            # The function should log appropriate warnings and info messages
            assert True  # Test passed if no exceptions were raised

        anyio.run(_test_inaccessible_post_handling)

    def test_post_with_content_handling(self):
        """Test handling of posts with actual content."""

        async def _test_post_with_content_handling():
            # Create a post with only text content (no images to avoid download issues in tests)
            text_data = PostDataText(
                type='text',
                modificator='',
                content='Some text content',
            )

            # Create a post with only text content to avoid complex mocking
            post_with_content = self.create_mock_post(
                post_id='content_post_123',
                title='Post with Content',
                has_access=True,
                data=[text_data],  # Only text, no images to download
            )

            # Download the post
            result = await self.download_manager._download_single_post(
                username='test_user',
                post=post_with_content,
            )

            # Should return True (successful processing)
            assert result is True

            # Check that NO empty marker file was created (normal post)
            post_dir = (
                self.temp_dir
                / 'test_user'
                / f'{post_with_content.created_at.date()} - Post with Content'
            )
            empty_marker_file = post_dir / 'EMPTY_POST_MARKER.txt'

            assert not empty_marker_file.exists()

            # Check that the post content HTML was created
            html_file = post_dir / 'post_content.html'
            assert html_file.exists()

        anyio.run(_test_post_with_content_handling)

    def test_post_location_generation(self):
        """Test that post location is generated correctly."""
        post = self.create_mock_post(
            post_id='test_post_123',
            title='Test Post Title',
        )

        location = self.download_manager._generate_post_location(
            username='test_user',
            post=post,
        )

        assert location.username == 'test_user'
        assert location.title == 'Test Post Title'
        assert location.full_name == f'{post.created_at.date()} - Test Post Title'
        assert (
            location.post_directory == self.temp_dir / 'test_user' / location.full_name
        )

    def test_empty_post_detection(self):
        """Test detection of empty posts."""
        # Test with completely empty post
        empty_post = self.create_mock_post(
            post_id='empty_post_123',
            title='Empty Post',
            data=[],
        )

        separated_data = self.download_manager._separate_post_content(empty_post)

        # Check that empty post is detected
        has_content = (
            len(separated_data.post_content) > 0
            or len(separated_data.files) > 0
            or len(separated_data.ok_videos) > 0
            or len(separated_data.videos) > 0
        )

        assert not has_content

    def test_post_with_valid_content_detection(self):
        """Test detection of posts with valid content."""
        # Create valid post data
        text_data = PostDataText(
            type='text',
            modificator='',
            content='Some text content',
        )

        # Test with post containing content
        post_with_content = self.create_mock_post(
            post_id='content_post_123',
            title='Post with Content',
            data=[text_data],
        )

        separated_data = self.download_manager._separate_post_content(post_with_content)

        # Check that content is detected
        has_content = (
            len(separated_data.post_content) > 0
            or len(separated_data.files) > 0
            or len(separated_data.ok_videos) > 0
            or len(separated_data.videos) > 0
        )

        assert has_content
        assert len(separated_data.post_content) == 1
