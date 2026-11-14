"""Host, write and response boundaries for the local library server."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypeAlias, cast
from urllib.parse import urlsplit

from aiohttp import web

from boosty_downloader.viewer.api_models import (
    ERROR_HOST_NOT_ALLOWED,
    ERROR_WRITE_NOT_ALLOWED,
    ErrorBody,
    ErrorResponse,
)
from boosty_downloader.viewer.pages import LibraryNotice, notice_page

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

_APP_POLICY: Final = (
    "default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; img-src 'self' data:; media-src 'self'; "
    "style-src 'self' 'unsafe-inline'; frame-src 'self'; frame-ancestors 'none'"
)
_WRITE_METHODS: Final = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
SocketAddressValues: TypeAlias = tuple[object, ...]
_IPAddress: TypeAlias = ipaddress.IPv4Address | ipaddress.IPv6Address
_PROXY_HEADERS: Final = frozenset(
    {
        'forwarded',
        'via',
        'x-real-ip',
        'x-client-ip',
        'x-cluster-client-ip',
        'cf-connecting-ip',
        'true-client-ip',
        'fastly-client-ip',
    }
)


@dataclass(frozen=True, slots=True)
class _Authority:
    host: str
    port: int | None


def _authority(value: str) -> _Authority | None:
    if not value or _has_whitespace_or_controls(value):
        return None
    if any(char in value for char in '/\\?#@,') or value.endswith(':'):
        return None
    try:
        parsed = urlsplit(f'//{value}')
        host, port = parsed.hostname, parsed.port
    except ValueError:
        return None
    if host is None or not _is_exact_authority(value, host, port):
        return None
    return _Authority(host.lower(), port)


def _has_whitespace_or_controls(value: str) -> bool:
    return any(char.isspace() or not char.isprintable() for char in value)


def _is_exact_authority(value: str, host: str, port: int | None) -> bool:
    name = host
    if ':' in host:
        name = f'[{host}]'
    if port is not None:
        port_text = value.rsplit(':', 1)[1]
        if not port_text.isascii() or not port_text.isdecimal():
            return False
        name += f':{port_text}'
    return value.lower() == name.lower()


def _request_authority(request: web.Request) -> _Authority | None:
    hosts = request.headers.getall('Host', [])
    if len(hosts) != 1:
        return None
    return _authority(hosts[0])


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def is_host_allowed(request: web.Request) -> bool:
    """Accept address literals and this computer's approved local names."""
    authority = _request_authority(request)
    if authority is None:
        return False
    name = authority.host.removesuffix('.')
    if name == 'localhost' or _is_ip(name):
        return True
    machine = socket.gethostname().lower().rstrip('.').removesuffix('.local')
    return name in {machine, f'{machine}.local'}


def is_address_host(request: web.Request) -> bool:
    """Allow local actions only through a literal address or localhost."""
    authority = _request_authority(request)
    if authority is None:
        return False
    name = authority.host.removesuffix('.')
    return name == 'localhost' or _is_ip(name)


def _ip_address(value: str | None) -> _IPAddress | None:
    if value is None:
        return None
    try:
        address = ipaddress.ip_address(value.split('%', 1)[0])
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _connection_address(request: web.Request) -> _IPAddress | None:
    if request.transport is None:
        return None
    address: object = request.transport.get_extra_info('sockname')
    if not isinstance(address, tuple):
        return None
    values = cast('SocketAddressValues', address)
    if not values or not isinstance(values[0], str):
        return None
    return _ip_address(values[0])


def is_same_machine(request: web.Request) -> bool:
    """Accept loopback or the connected local address without proxy headers."""
    if any(
        name.lower() in _PROXY_HEADERS or name.lower().startswith('x-forwarded-')
        for name in request.headers
    ):
        return False
    peer = _ip_address(request.remote)
    if peer is None:
        return False
    return peer.is_loopback or peer == _connection_address(request)


def is_open_allowed(request: web.Request) -> bool:
    """Require the local viewer's explicit origin before any desktop action."""
    return (
        is_origin_allowed(request, required=True)
        and is_write_allowed(request)
        and is_address_host(request)
        and is_same_machine(request)
    )


def _origin_authority(origin: str, scheme: str) -> _Authority | None:
    if _has_whitespace_or_controls(origin):
        return None
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return None
    if parsed.scheme != scheme or parsed.scheme not in {'http', 'https'}:
        return None
    if origin.lower() != f'{parsed.scheme}://{parsed.netloc}'.lower():
        return None
    return _authority(parsed.netloc)


def _effective_port(authority: _Authority, scheme: str) -> int:
    if authority.port is not None:
        return authority.port
    return 443 if scheme == 'https' else 80


def _is_same_origin(request: web.Request, origin: str) -> bool:
    host = _request_authority(request)
    source = _origin_authority(origin, request.scheme)
    if host is None or source is None or host.host != source.host:
        return False
    return _effective_port(host, request.scheme) == _effective_port(
        source, request.scheme
    )


def is_write_allowed(request: web.Request) -> bool:
    """Require JSON and reject origins or fetch metadata from another site."""
    if (
        len(request.headers.getall('Content-Type', [])) != 1
        or request.content_type != 'application/json'
    ):
        return False
    return is_origin_allowed(request)


def is_origin_allowed(request: web.Request, *, required: bool = False) -> bool:
    """Check explicit origin and fetch metadata without requiring a request body."""
    origins = request.headers.getall('Origin', [])
    if required and not origins:
        return False
    if len(origins) > 1 or (origins and not _is_same_origin(request, origins[0])):
        return False
    fetch_sites = request.headers.getall('Sec-Fetch-Site', [])
    return not fetch_sites or fetch_sites == ['same-origin']


def _local_address(request: web.Request) -> str:
    if request.transport is not None:
        address: object = request.transport.get_extra_info('sockname')
        if isinstance(address, tuple):
            values = cast('SocketAddressValues', address)
            if len(values) > 1 and isinstance(values[1], int):
                return f'http://localhost:{values[1]}/'
    return 'http://localhost/'


def _wrong_host(request: web.Request) -> web.Response:
    if 'text/html' in request.headers.get('Accept', '').lower():
        notice = LibraryNotice(
            'Open the viewer by its address',
            "Use localhost, this computer's IP address, or this computer's name.",
        )
        return web.Response(
            status=421,
            text=notice_page(notice, address=_local_address(request)),
            content_type='text/html',
            headers={'Cache-Control': 'no-store'},
        )
    body = ErrorResponse(
        error=ErrorBody(
            code=ERROR_HOST_NOT_ALLOWED, message='This Host is not allowed.'
        )
    )
    return web.json_response(body.model_dump(mode='json'), status=421)


@web.middleware
async def guard_requests(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Apply local-host and write checks before a route can handle the request."""
    if not is_host_allowed(request):
        return _wrong_host(request)
    if request.method in _WRITE_METHODS and not is_write_allowed(request):
        body = ErrorResponse(
            error=ErrorBody(
                code=ERROR_WRITE_NOT_ALLOWED, message='This write is not allowed.'
            )
        )
        return web.json_response(body.model_dump(mode='json'), status=403)
    return await handler(request)


async def secure_response(request: web.Request, response: web.StreamResponse) -> None:
    """Set headers at publication time, including errors and streamed files."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if request.path == '/media' or request.path.startswith('/media/'):
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    if 'Content-Security-Policy' not in response.headers:
        response.headers['Content-Security-Policy'] = _APP_POLICY
        response.headers['X-Frame-Options'] = 'DENY'
