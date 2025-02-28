"""The modules helps with path sanitization to make it work on different platforms"""

import re


def sanitize_string(string: str) -> str:
    """Remove unsafe filesystem characters from a string"""
    # Convert path to a string and sanitize it
    unsafe_chars = r'[<>:"/\\|?*]'
    return re.sub(unsafe_chars, '', str(string))
