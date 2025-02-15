"""
Post data types.

This module contains a class with all possible types of post data.

"""

from enum import Enum


class PostDataType(Enum):
    """
    General types of post data.

    This type determine the `shape` of post data.
    """

    text = 'text'
    image = 'image'
    video = 'video'
    link = 'link'
    ok_video = 'ok_video'
    file = 'file'
