"""
Custom exceptions for application-level download errors.

These classes standardize handling of any download failures from posts or resources,
wrapping lower-level errors into a unified application-level form.
"""


class ApplicationBaseDownloadError(Exception):
    """
    Base class for all application-level download errors.

    Each error instance is bound to a specific post that triggered it.

    Attributes
    ----------
    post_uuid : str
        Unique identifier of the post related to the error.

    """

    def __init__(self, post_uuid: str) -> None:
        super().__init__()
        self.post_uuid = post_uuid


class ApplicationFailedDownloadError(ApplicationBaseDownloadError):
    """
    Raised when downloading a specific resource from a post fails.

    Causes may include network errors, invalid URLs, or resource unavailability
    (e.g., a YouTube video becoming private).

    Attributes
    ----------
    resource : str
        Identifier or description of the resource that failed to download.
    message : str
        Human-readable details about the failure.

    """

    def __init__(self, post_uuid: str, resource: str, message: str) -> None:
        super().__init__(post_uuid)
        self.resource = resource
        self.message = message


class ApplicationCancelledError(ApplicationBaseDownloadError):
    """
    Raised when a download for a specific post is cancelled by the user.

    Typically stops the entire download process.
    """
