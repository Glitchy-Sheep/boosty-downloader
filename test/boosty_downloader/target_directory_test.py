"""Tests for target_directory configuration parameter"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

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
from boosty_downloader.src.yaml_configuration.config import DownloadSettings


class TestTargetDirectoryConfig(unittest.TestCase):
    """Test target_directory configuration parameter"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = Path(tempfile.mkdtemp())

        # Mock logger dependencies
        self.logger_dependencies = LoggerDependencies(
            logger=Mock(),
            failed_downloads_logger=Mock(),
        )

        # Mock network dependencies
        self.network_dependencies = NetworkDependencies(
            session=Mock(),
            api_client=Mock(),
            external_videos_downloader=Mock(),
        )

    def tearDown(self):
        """Clean up test fixtures"""
        # Clean up temp directory
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_relative_path_config(self):
        """Test that relative paths work correctly"""
        relative_path = Path('./custom-downloads')

        general_options = GeneralOptions(
            target_directory=relative_path,
            download_content_type_filters=list(DownloadContentTypeFilter),
            request_delay_seconds=2.5,
            preferred_video_quality=VideoQualityOption.medium,
        )

        download_manager = BoostyDownloadManager(
            general_options=general_options,
            logger_dependencies=self.logger_dependencies,
            network_dependencies=self.network_dependencies,
        )

        # Check that the path is converted to absolute
        assert download_manager._target_directory.is_absolute()
        assert download_manager._target_directory.name == 'custom-downloads'

    def test_absolute_path_config(self):
        """Test that absolute paths work correctly"""
        absolute_path = self.temp_dir / 'absolute-downloads'

        general_options = GeneralOptions(
            target_directory=absolute_path,
            download_content_type_filters=list(DownloadContentTypeFilter),
            request_delay_seconds=2.5,
            preferred_video_quality=VideoQualityOption.medium,
        )

        download_manager = BoostyDownloadManager(
            general_options=general_options,
            logger_dependencies=self.logger_dependencies,
            network_dependencies=self.network_dependencies,
        )

        # Check that the absolute path is preserved
        assert download_manager._target_directory.is_absolute()
        assert download_manager._target_directory == absolute_path.absolute()

    def test_directory_creation(self):
        """Test that target directory is created if it doesn't exist"""
        test_path = self.temp_dir / 'new-directory'

        # Ensure directory doesn't exist
        assert not test_path.exists()

        general_options = GeneralOptions(
            target_directory=test_path,
            download_content_type_filters=list(DownloadContentTypeFilter),
            request_delay_seconds=2.5,
            preferred_video_quality=VideoQualityOption.medium,
        )

        BoostyDownloadManager(
            general_options=general_options,
            logger_dependencies=self.logger_dependencies,
            network_dependencies=self.network_dependencies,
        )

        # Check that directory was created
        assert test_path.exists()
        assert test_path.is_dir()

    def test_config_integration(self):
        """Test that Config properly handles different path formats"""

        # Test relative path
        config_data = {
            'downloading_settings': {
                'target_directory': './test-relative',
            },
        }

        download_settings = DownloadSettings.model_validate(config_data['downloading_settings'])
        assert download_settings.target_directory == Path('./test-relative')

        # Test absolute path
        abs_path = str(self.temp_dir / 'test-absolute')
        config_data = {
            'downloading_settings': {
                'target_directory': abs_path,
            },
        }

        download_settings = DownloadSettings.model_validate(config_data['downloading_settings'])
        assert download_settings.target_directory == Path(abs_path)


if __name__ == '__main__':
    unittest.main()
