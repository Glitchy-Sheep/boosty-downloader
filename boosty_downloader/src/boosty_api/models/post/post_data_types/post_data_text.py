"""The module with textual representation of posts data"""

from boosty_downloader.src.boosty_api.models.post.base_post_data import BasePostData
from boosty_downloader.src.boosty_api.models.post.post_data_type import PostDataType


class PostDataText(BasePostData):
    """Textual content piece in posts"""

    type = PostDataType.text
    content: str
    modificator: str
