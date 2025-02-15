"""
The module contains a model for boosty 'post' data.

Only essentials fields defined for parsing purposes.
"""

from abc import ABC

from pydantic import BaseModel

from boosty_downloader.src.boosty_api.models.post.post_data_type import PostDataType


class BasePostData(BaseModel, ABC):
    """Base model for any data in posts"""

    type: PostDataType
