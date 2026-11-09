"""Names retained in a post's remote content-count metadata."""

from enum import Enum


class RemoteCounter(str, Enum):
    """Observed content categories, distinct from saved media inventory kinds."""

    platform_video = 'ok_video'
    external_video = 'video'
    image = 'image'
    file = 'file'
    audio = 'audio'
