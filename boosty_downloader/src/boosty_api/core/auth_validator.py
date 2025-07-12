"""Authentication validator for Boosty API"""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.src.loggers.logger_instances import downloader_logger

if TYPE_CHECKING:
    from boosty_downloader.src.boosty_api.models.post.posts_request import PostsResponse


class AuthValidationResult:
    """Result of authentication validation"""

    def __init__(
        self,
        is_valid: bool,
        issue_type: str | None = None,
        message: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        self.is_valid = is_valid
        self.issue_type = issue_type
        self.message = message
        self.suggestion = suggestion

    def log_issue(self) -> None:
        """Log authentication issue if present"""
        if not self.is_valid and self.message:
            downloader_logger.warning(f'Authentication issue: {self.message}')
            if self.suggestion:
                downloader_logger.info(f'Suggestion: {self.suggestion}')


class AuthValidator:
    """Validates authentication status based on API responses"""

    def __init__(self) -> None:
        self._total_posts_checked = 0
        self._inaccessible_posts_count = 0
        self._consecutive_empty_responses = 0
        self._last_responses: list[PostsResponse] = []

    def add_response(self, response: PostsResponse) -> None:
        """Add a response for analysis"""
        self._last_responses.append(response)
        # Keep only last 5 responses for analysis
        if len(self._last_responses) > 5:
            self._last_responses.pop(0)

        # Update statistics
        posts_count = len(response.posts)
        self._total_posts_checked += posts_count

        if posts_count == 0:
            self._consecutive_empty_responses += 1
        else:
            self._consecutive_empty_responses = 0

        # Count inaccessible posts
        for post in response.posts:
            if not post.has_access:
                self._inaccessible_posts_count += 1

    def validate_auth_status(self) -> AuthValidationResult:
        """
        Validate authentication status based on collected responses.

        Returns AuthValidationResult with validation status and recommendations.
        """
        # No data to analyze
        if not self._last_responses:
            return AuthValidationResult(True)

        # Check for pattern of only getting posts without access (highest priority)
        if self._total_posts_checked >= 10:  # Only check if we have enough data
            all_no_access = all(
                not post.has_access
                for response in self._last_responses
                for post in response.posts
            )

            if all_no_access and self._total_posts_checked > 0:
                return AuthValidationResult(
                    is_valid=False,
                    issue_type='no_access_to_posts',
                    message='No access to any posts from this author',
                    suggestion='This might indicate insufficient subscription level or authentication issues. Check your Boosty subscription status.',
                )

        # Check if all recent responses are empty (check before consecutive empty)
        recent_responses = self._last_responses[-3:]  # Last 3 responses
        if len(recent_responses) >= 3:
            all_empty = all(len(resp.posts) == 0 for resp in recent_responses)

            if all_empty:
                return AuthValidationResult(
                    is_valid=False,
                    issue_type='all_recent_empty',
                    message='All recent API responses are empty',
                    suggestion='This might indicate that the author has no accessible posts for your account or authentication has expired.',
                )

        # Check for consecutive empty responses
        if self._consecutive_empty_responses >= 3:
            return AuthValidationResult(
                is_valid=False,
                issue_type='consecutive_empty_responses',
                message='Received multiple empty responses in a row',
                suggestion='This might indicate authentication issues or rate limiting. Try refreshing your authentication tokens.',
            )

        # Check for high percentage of inaccessible posts
        if self._total_posts_checked > 0:
            inaccessible_percentage = (
                self._inaccessible_posts_count / self._total_posts_checked
            ) * 100

            if inaccessible_percentage > 50:  # More than 50% inaccessible
                return AuthValidationResult(
                    is_valid=False,
                    issue_type='high_inaccessible_percentage',
                    message=f'High percentage of inaccessible posts: {inaccessible_percentage:.1f}%',
                    suggestion='This might indicate authentication issues or insufficient subscription level. Check your Boosty account status.',
                )

        # All checks passed
        return AuthValidationResult(True)

    def get_statistics(self) -> dict[str, int | float]:
        """Get current statistics"""
        total_posts = self._total_posts_checked
        inaccessible_percentage = (
            (self._inaccessible_posts_count / total_posts * 100)
            if total_posts > 0
            else 0
        )

        return {
            'total_posts_checked': self._total_posts_checked,
            'inaccessible_posts_count': self._inaccessible_posts_count,
            'inaccessible_percentage': inaccessible_percentage,
            'consecutive_empty_responses': self._consecutive_empty_responses,
            'responses_analyzed': len(self._last_responses),
        }

    def reset(self) -> None:
        """Reset statistics for new analysis"""
        self._total_posts_checked = 0
        self._inaccessible_posts_count = 0
        self._consecutive_empty_responses = 0
        self._last_responses.clear()
