"""The module describes the form of a post of a user on boosty.to"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 Pydantic should know this type fully

from pydantic import ConfigDict
from pydantic.alias_generators import to_camel
from pydantic.main import BaseModel

from boosty_downloader.src.boosty_api.models.post.base_post_data import (
    BasePostData,  # noqa: TC001 Pydantic should know this type fully
)


class Post(BaseModel):
    """Post on boosty.to which also have data pieces"""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    has_access: bool

    signed_query: str

    data: list[BasePostData]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
