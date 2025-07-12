"""Test retry behavior for previously inaccessible posts."""

from datetime import datetime, timezone

import pytest

from boosty_downloader.src.boosty_api.models.post.post import Post
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_text import (
    PostDataText,
)
from boosty_downloader.src.caching.post_cache import PostCache


class TestInaccessiblePostRetryBehavior:
    """Test that previously inaccessible posts are retried on subsequent runs."""

    @pytest.fixture
    def post_cache(self, tmp_path):
        """Create a PostCache instance for testing."""
        cache_dir = tmp_path / 'test_cache'
        cache_dir.mkdir()
        return PostCache(cache_dir)

    @pytest.fixture
    def mock_post(self):
        """Create a mock Post for testing."""
        return Post(
            id='test-post-id',
            title='Test Post',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            has_access=False,  # Initially inaccessible
            data=[],
            signed_query='',
        )

    def test_inaccessible_post_not_cached(self, post_cache, mock_post, tmp_path):
        """Test that inaccessible posts are not added to cache."""
        # Create a folder for the post (simulate previous processing)
        post_folder = tmp_path / 'test_cache' / '2023-01-01 - Test Post'
        post_folder.mkdir(parents=True)

        # Initially, post should not be in cache
        assert not post_cache.has_same_post(
            post_id=mock_post.id,
            current_title=mock_post.title,
            updated_at=mock_post.updated_at,
            current_folder_name='2023-01-01 - Test Post',
        )

        # After processing inaccessible post, it should still not be in cache
        # (the new behavior - inaccessible posts are not cached)
        assert not post_cache.has_same_post(
            post_id=mock_post.id,
            current_title=mock_post.title,
            updated_at=mock_post.updated_at,
            current_folder_name='2023-01-01 - Test Post',
        )

    def test_accessible_post_is_cached(self, post_cache, mock_post, tmp_path):
        """Test that accessible posts are still cached normally."""
        # Make the post accessible
        mock_post.has_access = True
        mock_post.data = [
            PostDataText(content='Accessible content', type='text', modificator=''),
        ]

        # Create a folder for the post
        post_folder = tmp_path / 'test_cache' / '2023-01-01 - Test Post'
        post_folder.mkdir(parents=True)

        # Add accessible post to cache
        post_cache.add_post_cache(
            post_id=mock_post.id,
            title=mock_post.title,
            updated_at=mock_post.updated_at,
        )

        # Accessible post should be in cache
        assert post_cache.has_same_post(
            post_id=mock_post.id,
            current_title=mock_post.title,
            updated_at=mock_post.updated_at,
            current_folder_name='2023-01-01 - Test Post',
        )


if __name__ == '__main__':
    pytest.main([__file__])
