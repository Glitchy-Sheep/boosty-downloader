"""Usual video links (on youtube and other services)"""

from boosty_api.models.post.post_data_type import PostDataType

from boosty_downloader.src.boosty_api.models.post.base_post_data import BasePostData


class PostDataVideo(BasePostData):
    """Video content piece in posts"""

    type = PostDataType.video
    url: str
