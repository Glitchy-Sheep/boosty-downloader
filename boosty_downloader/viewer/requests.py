"""Strict JSON bodies and identities at the viewer boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from pydantic import TypeAdapter, ValidationError

if TYPE_CHECKING:
    from aiohttp import web

_RequestValue = TypeVar('_RequestValue')


class InvalidRequestError(ValueError):
    """An HTTP body or identity does not match the accepted contract."""


def require_no_query(request: web.Request) -> None:
    """Reject parameters that could suggest a different mutation selection."""
    if request.query:
        message = 'This route does not accept query parameters.'
        raise InvalidRequestError(message)


async def read_body(
    request: web.Request, adapter: TypeAdapter[_RequestValue]
) -> _RequestValue:
    """Validate UTF-8 JSON without echoing input values in error responses."""
    require_no_query(request)
    try:
        return adapter.validate_json(await request.read())
    except ValidationError as error:
        message = 'Invalid request body.'
        raise InvalidRequestError(message) from error


async def require_empty_request(request: web.Request) -> None:
    """Read-only progress accepts neither filters nor a body."""
    require_no_query(request)
    if await request.read():
        message = 'This route does not accept a request body.'
        raise InvalidRequestError(message)
