"""Opaque media IDs round-trip complete identities without becoming path syntax."""

import base64

import pytest

from boosty_downloader.domain.library_media import MediaIdentity
from boosty_downloader.viewer.media_identity import (
    decode_media_identity,
    media_identity,
)
from boosty_downloader.viewer.requests import InvalidRequestError


@pytest.mark.parametrize(
    ('post_id', 'media_id'),
    [
        ('full-post-one', 'audio:shared'),
        ('full-post-two', 'audio:shared'),
        ('пост %/#', 'external_video:https://example.test/а?x=1&x=2'),
    ],
)
def test_media_identity_preserves_both_full_keys(post_id: str, media_id: str) -> None:
    value = media_identity(post_id, media_id)
    assert decode_media_identity(value) == MediaIdentity(post_id, media_id)
    assert '/' not in value
    assert '=' not in value


@pytest.mark.parametrize('value', ['', '=', '../post', 'a+', 'a/', 'a b', 'a', 'пост'])
def test_media_identity_rejects_invalid_base64url(value: str) -> None:
    with pytest.raises(InvalidRequestError, match='Invalid media identity'):
        decode_media_identity(value)


@pytest.mark.parametrize(
    'body',
    [
        b'\xff',
        b'{',
        b'null',
        b'[]',
        b'{}',
        b'{"post":"p","media":""}',
        b'{"post":"","media":"m"}',
        b'{"post":true,"media":"m"}',
        b'{"post":"p","media":1}',
        b'{"post":"p","media":"m","extra":1}',
        b'{"post":"p","post":"p","media":"m"}',
        b'{"media":"m","post":"p"}',
        b'{ "post": "p", "media": "m" }',
        b'{"post":"\\ud800","media":"m"}',
    ],
)
def test_media_identity_rejects_invalid_or_noncanonical_documents(body: bytes) -> None:
    value = base64.urlsafe_b64encode(body).decode().rstrip('=')
    with pytest.raises(InvalidRequestError, match='Invalid media identity'):
        decode_media_identity(value)


def test_media_identity_rejects_redundant_padding() -> None:
    with pytest.raises(InvalidRequestError):
        decode_media_identity(media_identity('p', 'm') + '=')
