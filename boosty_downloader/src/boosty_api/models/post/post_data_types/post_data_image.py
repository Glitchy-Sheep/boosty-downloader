"""The module with image representation of posts data"""

from boosty_downloader.src.boosty_api.models.post.base_post_data import BasePostData
from boosty_downloader.src.boosty_api.models.post.post_data_type import PostDataType


class PostDataImage(BasePostData):
    """Image content piece in posts"""

    type = PostDataType.image
    url: str
    width: int
    height: int
