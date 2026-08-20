"""Filesystem-safe names: one policy for every directory and file we create."""

import errno
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

# Windows raises this instead of ENAMETOOLONG when the whole path
# exceeds MAX_PATH (260 units by default).
_WINERROR_PATH_TOO_LONG = 206

# Generated names always fit the per-name limit, so this error means
# the user's destination directory is too deep.
PATH_TOO_LONG_HINT = (
    'the full path exceeded the OS limit - '
    'move the destination folder closer to the drive root'
)


def is_path_too_long_error(error: BaseException | None) -> bool:
    """Check the error or any of its causes for the OS path-length failure."""
    while error is not None:
        if isinstance(error, OSError) and (
            error.errno == errno.ENAMETOOLONG
            or getattr(error, 'winerror', None) == _WINERROR_PATH_TOO_LONG
        ):
            return True
        error = error.__cause__
    return False


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
