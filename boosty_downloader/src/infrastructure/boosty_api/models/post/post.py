"""The module describes the form of a post of a user on boosty.to"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 Pydantic should know this type fully

from boosty_downloader.src.infrastructure.boosty_api.models.base import BoostyBaseDTO
from boosty_downloader.src.infrastructure.boosty_api.models.post.base_post_data import (
    BasePostData,  # noqa: TC001 Pydantic should know this type fully
)


class PostDTO(BoostyBaseDTO):
    """Post on boosty.to which also have data pieces"""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    has_access: bool

    signed_query: str

    data: list[BasePostData]
