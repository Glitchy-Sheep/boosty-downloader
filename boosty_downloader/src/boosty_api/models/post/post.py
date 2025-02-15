"""The module describes the form of a post of a user on boosty.to"""

from datetime import datetime

from pydantic.main import BaseModel

from boosty_downloader.src.boosty_api.models.post.base_post_data import BasePostData


class Post(BaseModel):
    """Post on boosty.to which also have data pieces"""

    id: str
    title: str
    created_at: datetime
    has_access: bool

    data: list[BasePostData]
