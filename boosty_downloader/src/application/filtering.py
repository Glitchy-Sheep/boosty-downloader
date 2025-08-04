"""Content type filters for the download manager."""

from enum import Enum


class DownloadContentTypeFilter(Enum):
    """
    Class that holds content type filters for the download manager

    They can be used to download only specific parts of content.
    """

    boosty_videos = 'boosty_videos'
    external_videos = 'external_videos'
    post_content = 'post_content'
    files = 'files'
