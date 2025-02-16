"""The module with file representation of posts data"""

from boosty_api.models.post.base_post_data import BasePostData
from boosty_api.models.post.post_data_type import PostDataType


class PostDataFile(BasePostData):
    """File content piece in posts"""

    type = PostDataType.file
    url: str
    title: str
