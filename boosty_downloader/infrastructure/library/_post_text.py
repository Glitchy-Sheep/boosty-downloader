"""Plain searchable text from canonical content, without rendered page notices."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.domain.stored_post import (
    LineBreak,
    ListBlock,
    MediaBlock,
    ParagraphBreak,
    TextBlock,
)

if TYPE_CHECKING:
    from boosty_downloader.domain.stored_post import (
        Block,
        ListItem,
        StoredPost,
        TextContent,
    )


def replace_search_controls(text: str) -> str:
    """Keep original offsets while replacing controls reserved by SQLite highlights."""
    return text.replace('\x00', ' ').replace('\x02', ' ').replace('\x03', ' ')


def fold_search_text(text: str) -> str:
    """Fold Russian yo without changing offsets; FTS handles case and Latin accents."""
    return replace_search_controls(text).replace('ё', 'е').replace('Ё', 'Е')


def post_body_text(record: StoredPost | None) -> str:
    """Retain body and list boundaries; omit media labels and generated notices."""
    if record is None:
        return ''
    return ''.join(_block_text(block) for block in record.blocks).strip()


def _block_text(block: Block) -> str:
    match block:
        case TextBlock() | ParagraphBreak():
            return _text_content(block)
        case ListBlock():
            return '\n'.join(_list_item_text(item) for item in block.items) + '\n'
        case MediaBlock():
            return '\n'


def _text_content(block: TextContent) -> str:
    match block:
        case ParagraphBreak():
            return '\n\n'
        case TextBlock():
            return ''.join(
                '\n' if isinstance(fragment, LineBreak) else fragment.text
                for fragment in block.fragments
            )


def _list_item_text(item: ListItem) -> str:
    own_text = ''.join(_text_content(block) for block in item.data)
    return '\n'.join(
        [own_text, *(_list_item_text(nested) for nested in item.nested_items)]
    )
