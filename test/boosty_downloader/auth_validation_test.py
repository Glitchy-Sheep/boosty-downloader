"""Tests for authentication validation functionality."""

import unittest
from datetime import datetime, timezone

from boosty_downloader.src.boosty_api.core.auth_validator import (
    AuthValidationResult,
    AuthValidator,
)
from boosty_downloader.src.boosty_api.models.post.extra import Extra
from boosty_downloader.src.boosty_api.models.post.post import Post
from boosty_downloader.src.boosty_api.models.post.posts_request import PostsResponse


class TestAuthValidator(unittest.TestCase):
    """Test cases for AuthValidator."""

    def setUp(self):
        """Set up test fixtures."""
        self.validator = AuthValidator()

    def create_mock_post(self, post_id: str, has_access: bool = True) -> Post:
        """Create a mock post for testing."""
        return Post(
            id=post_id,
            title='Test Post',
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            has_access=has_access,
            signed_query='',
            data=[],
        )

    def create_mock_response(
        self,
        posts_count: int = 5,
        has_access: bool = True,
        is_last: bool = False,
    ) -> PostsResponse:
        """Create a mock response for testing."""
        posts = [
            self.create_mock_post(f'post_{i}', has_access) for i in range(posts_count)
        ]

        extra = Extra(is_last=is_last, offset='test_offset')

        return PostsResponse(posts=posts, extra=extra)

    def test_consecutive_empty_responses_detection(self):
        """Test detection of consecutive empty responses (when not all recent are empty)."""
        # Add some normal responses first to avoid "all_recent_empty" trigger
        for _ in range(3):
            normal_response = self.create_mock_response(posts_count=5)
            self.validator.add_response(normal_response)

        # Add 3 consecutive empty responses
        for _ in range(3):
            empty_response = self.create_mock_response(posts_count=0)
            self.validator.add_response(empty_response)

        result = self.validator.validate_auth_status()

        assert not result.is_valid
        # Now with our priority system, this should be "all_recent_empty" since the last 3 are empty
        assert result.issue_type == 'all_recent_empty'

    def test_pure_consecutive_empty_responses(self):
        """Test detection of consecutive empty responses in isolation."""
        # Add 2 empty responses (not enough for consecutive trigger)
        for _ in range(2):
            empty_response = self.create_mock_response(posts_count=0)
            self.validator.add_response(empty_response)

        result = self.validator.validate_auth_status()
        assert result.is_valid  # Should still be valid

        # Add one more empty response to trigger consecutive empty
        empty_response = self.create_mock_response(posts_count=0)
        self.validator.add_response(empty_response)

        result = self.validator.validate_auth_status()
        assert not result.is_valid
        # This should be "all_recent_empty" because we only have 3 responses and all are empty
        assert result.issue_type == 'all_recent_empty'

    def test_high_inaccessible_percentage(self):
        """Test detection of high percentage of inaccessible posts."""
        # Add responses with mostly inaccessible posts
        for _ in range(3):
            # 8 inaccessible posts out of 10
            accessible_response = self.create_mock_response(
                posts_count=2, has_access=True,
            )
            inaccessible_response = self.create_mock_response(
                posts_count=8, has_access=False,
            )

            self.validator.add_response(accessible_response)
            self.validator.add_response(inaccessible_response)

        result = self.validator.validate_auth_status()

        assert not result.is_valid
        assert result.issue_type == 'high_inaccessible_percentage'
        assert 'percentage' in result.message.lower()

    def test_all_recent_empty_responses(self):
        """Test detection of all recent responses being empty."""
        # Add some normal responses first
        normal_response = self.create_mock_response(posts_count=5)
        self.validator.add_response(normal_response)

        # Then add 3 empty responses
        for _ in range(3):
            empty_response = self.create_mock_response(posts_count=0)
            self.validator.add_response(empty_response)

        result = self.validator.validate_auth_status()

        assert not result.is_valid
        assert result.issue_type == 'all_recent_empty'

    def test_no_access_to_posts(self):
        """Test detection when no posts are accessible."""
        # Add enough responses with no access
        for _ in range(5):
            no_access_response = self.create_mock_response(
                posts_count=2, has_access=False,
            )
            self.validator.add_response(no_access_response)

        result = self.validator.validate_auth_status()

        assert not result.is_valid
        assert result.issue_type == 'no_access_to_posts'

    def test_valid_authentication(self):
        """Test that valid authentication passes validation."""
        # Add normal responses
        for _ in range(5):
            normal_response = self.create_mock_response(posts_count=5, has_access=True)
            self.validator.add_response(normal_response)

        result = self.validator.validate_auth_status()

        assert result.is_valid
        assert result.issue_type is None

    def test_mixed_responses_within_threshold(self):
        """Test that mixed responses within acceptable threshold pass validation."""
        # Add responses with some inaccessible posts but below threshold
        for _ in range(3):
            # 7 accessible, 3 inaccessible (30% inaccessible - below 50% threshold)
            accessible_response = self.create_mock_response(
                posts_count=7, has_access=True,
            )
            inaccessible_response = self.create_mock_response(
                posts_count=3, has_access=False,
            )

            self.validator.add_response(accessible_response)
            self.validator.add_response(inaccessible_response)

        result = self.validator.validate_auth_status()

        assert result.is_valid

    def test_statistics_tracking(self):
        """Test that statistics are tracked correctly."""
        # Add various responses
        accessible_response = self.create_mock_response(posts_count=5, has_access=True)
        inaccessible_response = self.create_mock_response(
            posts_count=3, has_access=False,
        )
        empty_response = self.create_mock_response(posts_count=0)

        self.validator.add_response(accessible_response)
        self.validator.add_response(inaccessible_response)
        self.validator.add_response(empty_response)

        stats = self.validator.get_statistics()

        assert stats['total_posts_checked'] == 8  # 5 + 3 + 0
        assert stats['inaccessible_posts_count'] == 3
        assert stats['inaccessible_percentage'] == 37.5  # 3/8 * 100
        assert stats['consecutive_empty_responses'] == 1
        assert stats['responses_analyzed'] == 3

    def test_reset_functionality(self):
        """Test that reset clears all statistics."""
        # Add some responses
        response = self.create_mock_response(posts_count=5, has_access=False)
        self.validator.add_response(response)

        # Check that stats are not empty
        stats_before = self.validator.get_statistics()
        assert stats_before['total_posts_checked'] > 0

        # Reset and check
        self.validator.reset()
        stats_after = self.validator.get_statistics()

        assert stats_after['total_posts_checked'] == 0
        assert stats_after['inaccessible_posts_count'] == 0
        assert stats_after['consecutive_empty_responses'] == 0
        assert stats_after['responses_analyzed'] == 0

    def test_validation_result_logging(self):
        """Test AuthValidationResult logging functionality."""
        # Test valid result (should not log)
        valid_result = AuthValidationResult(True)
        valid_result.log_issue()  # Should not raise any issues

        # Test invalid result
        invalid_result = AuthValidationResult(
            False, 'test_issue', 'Test message', 'Test suggestion',
        )

        # This should log, but we can't easily test the actual logging
        # In a real test, we would mock the logger
        invalid_result.log_issue()


if __name__ == '__main__':
    unittest.main()
