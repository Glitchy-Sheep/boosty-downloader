"""Public media identities contain the full post identity and its local media key."""

import base64
import json


def media_identity(post_id: str, media_id: str) -> str:
    """Encode both identifiers without relying on delimiters inside a media key."""
    value = json.dumps(
        {'post': post_id, 'media': media_id}, ensure_ascii=False, separators=(',', ':')
    )
    return base64.urlsafe_b64encode(value.encode('utf-8')).decode('ascii').rstrip('=')
