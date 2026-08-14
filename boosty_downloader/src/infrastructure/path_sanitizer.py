"""Filesystem-safe names: one policy for every directory and file we create."""

import re
import unicodedata

# Byte budget for one path component: ext4/APFS allow 255 bytes,
# NTFS 255 UTF-16 chars; 240 leaves headroom on every platform.
MAX_NAME_BYTES = 240

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
        cleaned = 'untitled'

    result = cleaned + suffix
    if result.split('.', 1)[0].upper() in _RESERVED_NAMES:
        result = f'_{result}'
    return result
