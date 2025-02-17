"""The modules helps with path sanitization to make it work on different platforms"""

import re


def sanitize_string(path: str) -> str:
    """Sanitizes a path by replacing unsafe characters with underscores"""
    # Convert path to a string and sanitize it
    unsafe_chars = r'[<>:"/\\|?*.]'
    return re.sub(unsafe_chars, '_', str(path))
