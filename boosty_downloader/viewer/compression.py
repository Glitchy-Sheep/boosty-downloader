"""Response encoding negotiation that respects explicit quality exclusions."""

from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING

from aiohttp import web
from aiohttp.web_response import ContentCoding

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence


class ContentEncoding(str, Enum):
    """Representations used by the viewer's JSON and precompressed assets."""

    brotli = 'br'
    gzip = 'gzip'
    deflate = 'deflate'
    identity = 'identity'


_QUALITY = re.compile(r'(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)\Z')
_JSON_ENCODINGS = (
    ContentEncoding.gzip,
    ContentEncoding.deflate,
    ContentEncoding.identity,
)


def _quality(parameters: list[str]) -> float:
    if not parameters:
        return 1.0
    if len(parameters) != 1:
        return 0.0
    name, separator, value = parameters[0].strip().partition('=')
    if name.lower() != 'q' or not separator or not _QUALITY.fullmatch(value):
        return 0.0
    return float(value)


def _preferences(header: str) -> dict[str, float]:
    preferences: dict[str, float] = {}
    for entry in header.lower().split(','):
        name, *parameters = entry.split(';')
        name = name.strip()
        if name:
            quality = _quality(parameters)
            preferences[name] = min(preferences.get(name, quality), quality)
    return preferences


def _requested_encodings(
    preferences: dict[str, float], available: Sequence[ContentEncoding]
) -> dict[ContentEncoding, float]:
    candidates = {
        encoding: preferences.get(encoding.value, preferences.get('*', 0.0))
        for encoding in available
        if encoding != ContentEncoding.identity
    }
    if ContentEncoding.identity in available and 'identity' in preferences:
        candidates[ContentEncoding.identity] = preferences['identity']
    return candidates


def select_encoding(
    header: str, available: Sequence[ContentEncoding]
) -> ContentEncoding | None:
    """Prefer requested codings; use identity unless the client excludes it."""
    preferences = _preferences(header)
    candidates = _requested_encodings(preferences, available)
    preferred = max(candidates, key=lambda coding: candidates[coding], default=None)
    if preferred is not None and candidates[preferred] > 0:
        return preferred
    if (
        ContentEncoding.identity in available
        and preferences.get('identity', preferences.get('*', 1.0)) > 0
    ):
        return ContentEncoding.identity
    return None


def _compress_json(request: web.Request, response: web.StreamResponse) -> None:
    if not isinstance(response, web.Response):
        return
    if (
        response.content_type != 'application/json'
        or 'Content-Encoding' in response.headers
    ):
        return
    header = ','.join(request.headers.getall('Accept-Encoding', []))
    encoding = select_encoding(header, _JSON_ENCODINGS)
    if encoding is None:
        raise web.HTTPNotAcceptable(text='No acceptable response encoding.')
    response.headers.add('Vary', 'Accept-Encoding')
    if encoding != ContentEncoding.identity:
        response.enable_compression(force=ContentCoding(encoding.value))


@web.middleware
async def compress_json_responses(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Compress JSON responses, including structured refusals from the guards."""
    response = await handler(request)
    _compress_json(request, response)
    return response
