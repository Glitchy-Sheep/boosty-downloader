"""Structured expected failures without storage paths in HTTP responses."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from aiohttp import web

from boosty_downloader.domain.library_errors import (
    LibraryMarkConflictError,
    LibraryReadError,
    LibraryWriteError,
)
from boosty_downloader.viewer.api_models import (
    ERROR_NOT_FOUND,
    ErrorBody,
    ErrorResponse,
)
from boosty_downloader.viewer.mark_progress import MarksBusyError, MarksClosingError
from boosty_downloader.viewer.query import InvalidQueryError
from boosty_downloader.viewer.requests import InvalidRequestError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pydantic import BaseModel

ERROR_INVALID_QUERY: Final = 'invalid_query'
ERROR_INVALID_REQUEST: Final = 'invalid_request'
ERROR_MARK_CONFLICT: Final = 'mark_conflict'
ERROR_MARKS_BUSY: Final = 'marks_busy'
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
async def handle_library_errors(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Keep invalid input, absent resources and storage conflicts distinct."""
    try:
        return await handler(request)
    except (InvalidQueryError, InvalidRequestError) as error:
        return _input_failure(error)
    except (MarksBusyError, MarksClosingError) as error:
        return _bulk_conflict(error)
    except LibraryMarkConflictError:
        return error_response(
            409,
            ERROR_MARK_CONFLICT,
            'The requested mark is not available for this item.',
        )
    except (LibraryReadError, LibraryWriteError) as error:
        return _storage_failure(error)
    except web.HTTPNotFound:
        return error_response(404, ERROR_NOT_FOUND, 'Not found.')


def _input_failure(error: InvalidQueryError | InvalidRequestError) -> web.Response:
    match error:
        case InvalidQueryError():
            return error_response(400, ERROR_INVALID_QUERY, str(error))
        case InvalidRequestError():
            return error_response(400, ERROR_INVALID_REQUEST, str(error))


def _storage_failure(error: LibraryReadError | LibraryWriteError) -> web.Response:
    _LOGGER.error(
        'Cannot complete the requested library operation',
        exc_info=(type(error), error, error.__traceback__),
    )
    match error:
        case LibraryReadError():
            message = 'The library data cannot be read.'
        case LibraryWriteError():
            message = 'The library marks cannot be saved.'
    return error_response(409, ERROR_LIBRARY_UNAVAILABLE, message)


def _bulk_conflict(error: MarksBusyError | MarksClosingError) -> web.Response:
    match error:
        case MarksBusyError():
            return error_response(409, ERROR_MARKS_BUSY, str(error))
        case MarksClosingError():
            return error_response(409, ERROR_LIBRARY_UNAVAILABLE, str(error))
