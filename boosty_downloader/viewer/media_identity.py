"""Public media identities contain the full post identity and its local media key."""

import base64
import binascii
import json
from re import fullmatch

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from boosty_downloader.domain.library_media import MediaIdentity
from boosty_downloader.viewer.requests import InvalidRequestError


class _IdentityValue(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    post: str = Field(min_length=1)
    media: str = Field(min_length=1)


def media_identity(post_id: str, media_id: str) -> str:
    """Encode both identifiers without relying on delimiters inside a media key."""
    value = json.dumps(
        {'post': post_id, 'media': media_id}, ensure_ascii=False, separators=(',', ':')
    )
    return base64.urlsafe_b64encode(value.encode('utf-8')).decode('ascii').rstrip('=')


def decode_media_identity(value: str) -> MediaIdentity:
    """Accept only canonical unpadded IDs emitted by this API, never paths."""
    if fullmatch(r'[A-Za-z0-9_-]+', value) is None:
        message = 'Invalid media identity.'
        raise InvalidRequestError(message)
    try:
        data = base64.b64decode(
            value + '=' * (-len(value) % 4), altchars=b'-_', validate=True
        )
        identity = _IdentityValue.model_validate_json(data)
    except (binascii.Error, ValidationError) as error:
        message = 'Invalid media identity.'
        raise InvalidRequestError(message) from error
    if media_identity(identity.post, identity.media) != value:
        message = 'Invalid media identity.'
        raise InvalidRequestError(message)
    return MediaIdentity(identity.post, identity.media)
