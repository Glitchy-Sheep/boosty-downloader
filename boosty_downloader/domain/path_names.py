"""Portable names for files and post folders."""

import re
import unicodedata
from typing import Final

# Byte budget for one path component: ext4/APFS allow 255 bytes,
# NTFS 255 UTF-16 chars; 240 leaves headroom on every platform.
MAX_NAME_BYTES = 240
_EMPTY_FILENAME_STEM: Final = 'untitled'

# <>:"/\|?* are forbidden on Windows; control chars (newlines, tabs)
# are forbidden there too and unreadable everywhere else.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')

# Windows refuses these base names even with an extension (CON.txt).
_RESERVED_NAMES = frozenset(
    {'CON', 'PRN', 'AUX', 'NUL'}
    | {f'COM{i}' for i in range(1, 10)}
    | {f'LPT{i}' for i in range(1, 10)}
)


def sanitize_filename(
    name: str,
    *,
    suffix: str = '',
    max_bytes: int = MAX_NAME_BYTES,
) -> str:
    """
    Turn arbitrary text into a name safe for every supported filesystem.

    `suffix` is a caller-owned tail (a file extension or a dedup marker
    like ' (a2dd6942)') that survives verbatim: only `name` is cleaned
    and byte-truncated so the whole result fits `max_bytes`.
    """
    cleaned = unicodedata.normalize('NFC', name)
    cleaned = _UNSAFE_CHARS.sub('', cleaned)
    cleaned = cleaned.strip().rstrip('. ')

    budget = max(max_bytes - len(suffix.encode('utf-8')), 0)
    encoded = cleaned.encode('utf-8')
    if len(encoded) > budget:
        # A byte cut may land inside a multi-byte char: ignore the tail.
        cleaned = encoded[:budget].decode('utf-8', errors='ignore')
        cleaned = cleaned.rstrip('. ')

    if not cleaned:
        cleaned = _EMPTY_FILENAME_STEM

    result = cleaned + suffix
    if result.split('.', 1)[0].upper() in _RESERVED_NAMES:
        result = f'_{result}'
    return result


def compose_filename(stem: str, *, extension: str = '', marker: str = '') -> str:
    """
    Build one safe filename within the shared byte budget.

    The caller supplies a short, filesystem-safe collision marker. The extension is cleaned and shortened only when needed to leave room for the marker and a non-empty stem.
    """
    suffix_budget = (
        MAX_NAME_BYTES
        - len(marker.encode('utf-8'))
        - len(_EMPTY_FILENAME_STEM.encode('utf-8'))
    )
    extension = (
        sanitize_filename(extension, max_bytes=suffix_budget) if extension else ''
    )
    tail = marker + extension
    name = sanitize_filename(stem, suffix=tail)
    if len(name.encode('utf-8')) > MAX_NAME_BYTES:
        # Windows device names need room for their leading underscore.
        name = sanitize_filename(stem, suffix=tail, max_bytes=MAX_NAME_BYTES - 1)
    return name
