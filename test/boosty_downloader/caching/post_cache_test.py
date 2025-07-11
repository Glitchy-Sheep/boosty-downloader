"""Tests for PostCache functionality."""

import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from boosty_downloader.src.caching.post_cache import PostCache


class TestPostCache(unittest.TestCase):
    """Test cases for PostCache."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.cache = PostCache(self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        self.cache.close()
        # Clean up temp directory recursively
        shutil.rmtree(self.temp_dir)

    def test_add_and_retrieve_post_cache(self):
        """Test adding and retrieving posts from cache."""
        post_id = 'test_post_123'
        title = 'Test Post'
        datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        updated_at = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Add post to cache
        self.cache.add_post_cache(post_id, title, updated_at)

        # Create folder to simulate existing post
        folder_name = '2023-01-01 - Test Post'
        post_folder = self.temp_dir / folder_name
        post_folder.mkdir()

        # Check if post exists in cache
        assert self.cache.has_same_post(
            post_id=post_id,
            current_title=title,
            updated_at=updated_at,
            current_folder_name=folder_name,
        )

    def test_updated_post_not_in_cache(self):
        """Test that updated post is not considered as cached."""
        post_id = 'test_post_123'
        title = 'Test Post'
        datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        original_updated_at = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        new_updated_at = datetime(2023, 1, 2, 12, 0, 0, tzinfo=timezone.utc)

        # Add post to cache with original date
        self.cache.add_post_cache(post_id, title, original_updated_at)

        # Create folder to simulate existing post
        folder_name = '2023-01-01 - Test Post'
        post_folder = self.temp_dir / folder_name
        post_folder.mkdir()

        # Check with new updated_at date - should not be in cache
        assert not self.cache.has_same_post(
            post_id=post_id,
            current_title=title,
            updated_at=new_updated_at,
            current_folder_name=folder_name,
        )

    def test_missing_folder_removes_from_cache(self):
        """Test that missing folder triggers cache cleanup."""
        post_id = 'test_post_123'
        title = 'Test Post'
        datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        updated_at = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Add post to cache
        self.cache.add_post_cache(post_id, title, updated_at)

        # Don't create folder - simulate missing post
        folder_name = '2023-01-01 - Test Post'

        # Check if post exists - should return False and clean cache
        assert not self.cache.has_same_post(
            post_id=post_id,
            current_title=title,
            updated_at=updated_at,
            current_folder_name=folder_name,
        )

        # Create folder now
        post_folder = self.temp_dir / folder_name
        post_folder.mkdir()

        # Check again - should still be False since cache was cleaned
        assert not self.cache.has_same_post(
            post_id=post_id,
            current_title=title,
            updated_at=updated_at,
            current_folder_name=folder_name,
        )

    def test_update_post_cache(self):
        """Test updating existing post in cache."""
        post_id = 'test_post_123'
        title = 'Test Post'
        datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        old_updated_at = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        new_updated_at = datetime(2023, 1, 2, 12, 0, 0, tzinfo=timezone.utc)

        # Add post to cache
        self.cache.add_post_cache(post_id, title, old_updated_at)

        # Update post in cache
        self.cache.add_post_cache(post_id, title, new_updated_at)

        # Create folder to simulate existing post
        folder_name = '2023-01-01 - Test Post'
        post_folder = self.temp_dir / folder_name
        post_folder.mkdir()

        # Check with old date - should not be in cache
        assert not self.cache.has_same_post(
            post_id=post_id,
            current_title=title,
            updated_at=old_updated_at,
            current_folder_name=folder_name,
        )

        # Check with new date - should be in cache
        assert self.cache.has_same_post(
            post_id=post_id,
            current_title=title,
            updated_at=new_updated_at,
            current_folder_name=folder_name,
        )

    def test_different_posts_with_same_title(self):
        """Test that different posts with same title are handled correctly."""
        post_id_1 = 'test_post_123'
        post_id_2 = 'test_post_456'
        title = 'Same Title'
        datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        datetime(2023, 1, 2, 10, 0, 0, tzinfo=timezone.utc)
        updated_at = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Add both posts to cache
        self.cache.add_post_cache(post_id_1, title, updated_at)
        self.cache.add_post_cache(post_id_2, title, updated_at)

        # Create folders for both posts (different dates due to different created_at)
        folder_name_1 = '2023-01-01 - Same Title'
        folder_name_2 = '2023-01-02 - Same Title'

        post_folder_1 = self.temp_dir / folder_name_1
        post_folder_2 = self.temp_dir / folder_name_2
        post_folder_1.mkdir()
        post_folder_2.mkdir()

        # Check both posts individually
        assert self.cache.has_same_post(
            post_id=post_id_1,
            current_title=title,
            updated_at=updated_at,
            current_folder_name=folder_name_1,
        )
        assert self.cache.has_same_post(
            post_id=post_id_2,
            current_title=title,
            updated_at=updated_at,
            current_folder_name=folder_name_2,
        )

    def test_post_title_rename(self):
        """Test that folder is renamed when post title changes."""
        post_id = 'test_post_123'
        old_title = 'Old Title'
        new_title = 'New Title'
        created_at = datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        old_updated_at = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        new_updated_at = datetime(2023, 1, 2, 12, 0, 0, tzinfo=timezone.utc)

        # Add post to cache with old title
        self.cache.add_post_cache(post_id, old_title, old_updated_at)

        # Create folder with old title
        old_folder_name = '2023-01-01 - Old Title'
        old_folder = self.temp_dir / old_folder_name
        old_folder.mkdir()

        # Simulate checking post with new title and updated_at
        new_folder_name = '2023-01-01 - New Title'

        # has_same_post should return False when title changes (need re-download)
        assert not self.cache.has_same_post(
            post_id=post_id,
            current_title=new_title,
            updated_at=new_updated_at,
            current_folder_name=new_folder_name,
        )

        # Explicitly call ensure_folder_name_matches to rename folder
        self.cache.ensure_folder_name_matches(
            post_id=post_id,
            current_title=new_title,
            created_at=created_at,
        )

        # Check that old folder was renamed to new folder
        assert not old_folder.exists()
        assert (self.temp_dir / new_folder_name).exists()

    def test_ensure_folder_name_matches(self):
        """Test ensure_folder_name_matches method separately."""
        post_id = 'test_post_123'
        old_title = 'Old Title'
        new_title = 'New Title'
        created_at = datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        updated_at = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Add post to cache with old title
        self.cache.add_post_cache(post_id, old_title, updated_at)

        # Create folder with old title
        old_folder_name = '2023-01-01 - Old Title'
        old_folder = self.temp_dir / old_folder_name
        old_folder.mkdir()

        # Call ensure_folder_name_matches with new title
        self.cache.ensure_folder_name_matches(
            post_id=post_id,
            current_title=new_title,
            created_at=created_at,
        )

        # Check that folder was renamed
        new_folder_name = '2023-01-01 - New Title'
        assert not old_folder.exists()
        assert (self.temp_dir / new_folder_name).exists()

    def test_ensure_folder_name_matches_no_change(self):
        """Test that ensure_folder_name_matches does nothing when title unchanged."""
        post_id = 'test_post_123'
        title = 'Same Title'
        created_at = datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        updated_at = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Add post to cache
        self.cache.add_post_cache(post_id, title, updated_at)

        # Create folder
        folder_name = '2023-01-01 - Same Title'
        folder = self.temp_dir / folder_name
        folder.mkdir()

        # Call ensure_folder_name_matches with same title
        self.cache.ensure_folder_name_matches(
            post_id=post_id,
            current_title=title,
            created_at=created_at,
        )

        # Check that folder still exists and wasn't renamed
        assert folder.exists()

    def test_ensure_folder_name_matches_no_cache(self):
        """Test that ensure_folder_name_matches does nothing when post not in cache."""
        post_id = 'test_post_123'
        title = 'Test Title'
        created_at = datetime(2023, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

        # Don't add post to cache

        # Create folder
        folder_name = '2023-01-01 - Test Title'
        folder = self.temp_dir / folder_name
        folder.mkdir()

        # Call ensure_folder_name_matches
        self.cache.ensure_folder_name_matches(
            post_id=post_id,
            current_title=title,
            created_at=created_at,
        )

        # Check that folder still exists (no rename happened)
        assert folder.exists()


if __name__ == '__main__':
    unittest.main()
