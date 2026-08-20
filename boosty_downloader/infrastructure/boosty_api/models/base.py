"""Base model for all Boosty API DTOs."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class BoostyBaseDTO(BaseModel):
    """
    Base class for all Boosty API data transfer objects.

    Provides common configuration:
    - alias_generator: Converts snake_case fields to camelCase for JSON
    - populate_by_name: Allows using both snake_case and camelCase
    - from_attributes: Enables ORM mode for attribute access
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
