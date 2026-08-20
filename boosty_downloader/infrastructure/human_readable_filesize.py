"""Module with functions for human-readable file size representation"""

from __future__ import annotations


def human_readable_size(size: float | None, decimal_places: int = 2) -> str:
    """
    Return a human-readable string representing the size of a file.

    Usage example:
        path = Path("example.txt")

        file_size = path.stat().st_size  # Get file size in bytes
        print(human_readable_size(file_size))
    """
    if size is None:
        return 'N/A'

    kb_size = 1024

    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < kb_size:
            return f'{size:.{decimal_places}f} {unit}'
        size /= kb_size
    return f'{size:.{decimal_places}f} PB'
