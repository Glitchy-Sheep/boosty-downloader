"""Module with link representation of posts data"""

from boosty_api.models.post.base_post_data import BasePostData
from boosty_api.models.post.post_data_type import PostDataType


class PostDataLink(BasePostData):
    """Link content piece in posts"""

    type = PostDataType.link
    url: str
    content: str
    explicit: bool
