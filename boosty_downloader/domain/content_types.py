"""The parts a post is made of, as the downloader and the cache tell them apart."""

from enum import Enum


class DownloadContentTypeFilter(Enum):
    """
    Content type filters for the download manager.

    They can be used to download only specific parts of content.
    """

    # -------------------------------------------------------------------
    # --------------------------- WARNING !!! ---------------------------
    # -------------------------------------------------------------------
    #
    # If you add any new content type filters here, please ensure that:
    # 1. You updated cache logic accordingly
    # 2. You updated all the use cases that use this filter
    # 3. You checked all other places in which those filters were used before

    boosty_videos = 'boosty_videos'
    external_videos = 'external_videos'
    post_content = 'post_content'
    files = 'files'
    audio = 'audio'
