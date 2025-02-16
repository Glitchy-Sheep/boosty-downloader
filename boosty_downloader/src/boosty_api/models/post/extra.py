"""Models for meta info about posts or requests to boosty.to"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Extra(BaseModel):
    """Meta info for posts request, can be used for pagination mainly"""

    is_last: bool
    offset: str

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
