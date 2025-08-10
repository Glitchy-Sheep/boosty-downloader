"""
Contains the mapper function for converting Boosty API post data lists.

This module is responsible for transforming the Boosty API's list representation
to the domain's PostDataChunkTextualList object:

- unordered list example
    - one
    - two
- ...

1. ordered list example
    1. one
    2. two
2. ...
"""

from boosty_downloader.src.application.mappers.link_header_text import (
    to_domain_text_chunk,
)
from boosty_downloader.src.domain.post_data_chunks import (
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_list import (
    BoostyPostDataListDTO,
    BoostyPostDataListItemDTO,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_text import (
    BoostyPostDataTextDTO,
)


def to_domain_list_chunk(post_list: BoostyPostDataListDTO) -> PostDataChunkTextualList:
    """Convert API PostDataList to domain PostDataChunkTextualList."""

    def convert_list_item(
        api_item: BoostyPostDataListItemDTO,
    ) -> PostDataChunkTextualList.ListItem:
        """Recursively convert API list item to domain list item."""
        # Convert data items to domain text chunks
        domain_data: list[PostDataChunkText] = []
        for data_item in api_item.data:
            if data_item.type == 'text':
                # Create proper DTO object for the text mapper
                text_dto = BoostyPostDataTextDTO(
                    type='text',
                    content=data_item.content,
                    modificator=data_item.modificator or '',
                )
                text_fragments = to_domain_text_chunk(text_dto)

                # Create a PostDataChunkText with the text fragments
                text_chunk = PostDataChunkText(text_fragments=text_fragments)
                domain_data.append(text_chunk)

        # Recursively convert nested items
        nested_items = [
            convert_list_item(nested_item) for nested_item in api_item.items
        ]

        return PostDataChunkTextualList.ListItem(
            data=domain_data, nested_items=nested_items
        )

    # Convert all items
    domain_items = [convert_list_item(api_item) for api_item in post_list.items]

    return PostDataChunkTextualList(items=domain_items)
