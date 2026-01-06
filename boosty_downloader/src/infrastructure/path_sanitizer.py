"""The modules helps with path sanitization to make it work on different platforms"""

import re


def sanitize_string(string: str, max_bytes: int = 200) -> str:
    """Remove unsafe filesystem characters from a string and truncate to fit byte limit"""
    # Convert path to a string and sanitize it
    unsafe_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(unsafe_chars, '', str(string))

    if len(sanitized.encode('utf-8')) > max_bytes:
        sanitized = sanitized.encode('utf-8')[:max_bytes].decode(
            'utf-8', errors='ignore'
        )
        sanitized = sanitized.rstrip()

    return sanitized
