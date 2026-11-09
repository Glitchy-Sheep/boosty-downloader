"""Structured expected failures without storage paths in HTTP responses."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from aiohttp import web

from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.viewer.api_models import (
    ERROR_NOT_FOUND,
    ErrorBody,
    ErrorResponse,
)
from boosty_downloader.viewer.query import InvalidQueryError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pydantic import BaseModel

ERROR_INVALID_QUERY: Final = 'invalid_query'
ERROR_LIBRARY_UNAVAILABLE: Final = 'library_unavailable'
_COMPRESSION_THREAD_THRESHOLD: Final = 64 * 1024
_LOGGER = logging.getLogger(__name__)


def model_response(model: BaseModel) -> web.Response:
    """Serialize model JSON directly and compress large answers off the event loop."""
    return web.Response(
        text=model.model_dump_json(),
        content_type='application/json',
        zlib_executor_size=_COMPRESSION_THREAD_THRESHOLD,
    )


def error_response(status: int, code: str, message: str) -> web.Response:
    """Serialize the common failure envelope."""
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return web.json_response(body.model_dump(mode='json'), status=status)


@web.middleware
async def handle_read_errors(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Keep absent resources distinct from damaged or unreadable library data."""
    try:
        return await handler(request)
    except InvalidQueryError as error:
        return error_response(400, ERROR_INVALID_QUERY, str(error))
    except LibraryReadError:
        _LOGGER.exception('Cannot read the requested library data')
        return error_response(
            409, ERROR_LIBRARY_UNAVAILABLE, 'The library data cannot be read.'
        )
    except web.HTTPNotFound:
        return error_response(404, ERROR_NOT_FOUND, 'Not found.')
