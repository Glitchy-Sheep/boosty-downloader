"""Allow web, mail and relative links in author-supplied page content."""

import re
from typing import Final

_ALLOWED_SCHEMES: Final = frozenset({'http', 'https', 'mailto'})
_SCHEME_PREFIX: Final = re.compile(r'^([A-Za-z][A-Za-z0-9+.-]*):')
_C0_CONTROL_OR_SPACE: Final = ''.join(chr(code) for code in range(0x21))
_TAB_OR_NEWLINE: Final = str.maketrans('', '', '\t\n\r')


def safe_href(url: str | None) -> str | None:
    """Keep allowed links, judging schemes after browser URL whitespace cleanup."""
    if not url:
        return None
    candidate = url.strip(_C0_CONTROL_OR_SPACE).translate(_TAB_OR_NEWLINE)
    scheme = _SCHEME_PREFIX.match(candidate)
    if scheme is not None and scheme[1].lower() not in _ALLOWED_SCHEMES:
        return None
    return url
