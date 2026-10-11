"""Build and recognize post folders without accessing the filesystem."""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Final

from boosty_downloader.domain.path_names import MAX_NAME_BYTES, sanitize_filename

if TYPE_CHECKING:
    from datetime import datetime

_POST_ID_PREFIX_LENGTH: Final = 8
_POST_ID_PREFIX_PATTERN = rf'[A-Za-z0-9_-]{{1,{_POST_ID_PREFIX_LENGTH}}}'
_POST_FOLDER_PATTERN = re.compile(
    r'(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}) - '
    r'(?P<title>[^<>:"/\\|?*\x00-\x1f\x7f]+) '
    rf'\((?P<post_id_prefix>{_POST_ID_PREFIX_PATTERN})\)'
)


def get_post_id_prefix(post_id: str) -> str:
    """Return a case-sensitive folder hint; reject unrepresentable prefixes."""
    prefix = post_id[:_POST_ID_PREFIX_LENGTH]
    if re.fullmatch(_POST_ID_PREFIX_PATTERN, prefix) is None:
        msg = 'Post ID prefix must contain 1-8 ASCII letters, digits, hyphens or underscores'
        raise ValueError(msg)
    return prefix


def compose_post_directory_name(
    title: str, created_at: datetime, post_id: str, *, collision: int = 0
) -> str:
    """
    Build 'YYYY-MM-DD - Title (id8)' within the portable byte budget.

    The date stays in the supplied timezone. collision counts occupied choices: 0 keeps the base name, 1 adds [2], and 2 adds [3]. Invalid prefixes or collision values raise ValueError.
    """
    marker = _collision_marker(collision)
    prefix = f'{created_at.date()} - '
    suffix = f'{marker} ({get_post_id_prefix(post_id)})'
    budget = MAX_NAME_BYTES - len(prefix.encode('utf-8'))
    clean_title = _fit_title(title.strip() or 'No title', suffix, budget)
    return prefix + clean_title


def _collision_marker(collision: int) -> str:
    if type(collision) is not int or collision < 0:
        msg = 'Collision count must be a non-negative integer'
        raise ValueError(msg)
    if collision == 0:
        return ''
    return f' [{collision + 1}]'


def _fit_title(title: str, suffix: str, budget: int) -> str:
    name = sanitize_filename(title, suffix=suffix, max_bytes=budget)
    if len(name.encode('utf-8')) > budget:
        # A Windows device-name prefix needs room for its leading underscore.
        name = sanitize_filename(title, suffix=suffix, max_bytes=budget - 1)
    if len(name.encode('utf-8')) > budget:
        msg = 'Collision count leaves no room for a safe post title'
        raise ValueError(msg)
    return name


def parse_post_folder_id(name: str) -> str | None:
    """
    Extract the short ID from a complete post-folder basename, or return None.

    Existing names may use decomposed Unicode or exceed today's generation budget. The title, including any collision counter, does not determine the post's identity.
    """
    match = _POST_FOLDER_PATTERN.fullmatch(name)
    if match is None or not match.group('title').strip():
        return None
    try:
        date.fromisoformat(match.group('date'))
    except ValueError:
        return None
    return match.group('post_id_prefix')
