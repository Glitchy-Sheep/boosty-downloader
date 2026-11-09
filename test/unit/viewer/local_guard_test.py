"""Desktop actions require an address-literal viewer on this computer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from aiohttp.test_utils import make_mocked_request
from multidict import CIMultiDict

from boosty_downloader.viewer.guard import (
    is_address_host,
    is_open_allowed,
    is_origin_allowed,
    is_same_machine,
)

if TYPE_CHECKING:
    from aiohttp import web


def _request(
    peer: str | None = '127.0.0.1',
    local: str | None = '127.0.0.1',
    headers: CIMultiDict[str] | dict[str, str] | None = None,
) -> web.Request:
    addresses = {
        'peername': None if peer is None else (peer, 50123),
        'sockname': None if local is None else (local, 8314),
    }

    def get_extra_info(name: str, default: object = None) -> object:
        return addresses.get(name, default)

    transport = Mock()
    transport.get_extra_info.side_effect = get_extra_info
    return make_mocked_request('POST', '/', headers=headers or {}, transport=transport)


@dataclass(frozen=True, slots=True)
class _PeerCase:
    peer: str | None
    local: str | None
    allowed: bool


@pytest.mark.parametrize(
    'case',
    [
        _PeerCase('127.0.0.1', None, allowed=True),
        _PeerCase('127.42.1.9', '0.0.0.0', allowed=True),  # noqa: S104 - mock socket
        _PeerCase('::1', '::', allowed=True),
        _PeerCase('::ffff:127.0.0.1', '::', allowed=True),
        _PeerCase('192.168.2.4', '192.168.2.4', allowed=True),
        _PeerCase('::ffff:192.168.2.4', '192.168.2.4', allowed=True),
        _PeerCase('192.168.2.4', '::ffff:192.168.2.4', allowed=True),
        _PeerCase('fe80::1%en0', 'fe80::1%3', allowed=True),
        _PeerCase('192.168.2.5', '192.168.2.4', allowed=False),
        _PeerCase('192.168.2.4', '0.0.0.0', allowed=False),  # noqa: S104 - mock socket
        _PeerCase('2001:db8::2', '2001:db8::1', allowed=False),
        _PeerCase('192.168.2.4', None, allowed=False),
        _PeerCase(None, '127.0.0.1', allowed=False),
        _PeerCase('invalid', 'invalid', allowed=False),
    ],
)
def test_same_machine_address_table(case: _PeerCase) -> None:
    assert is_same_machine(_request(case.peer, case.local)) is case.allowed


@pytest.mark.parametrize(
    'header',
    [
        'Forwarded',
        'Via',
        'X-Real-IP',
        'X-Client-IP',
        'X-Cluster-Client-IP',
        'CF-Connecting-IP',
        'True-Client-IP',
        'Fastly-Client-IP',
        'X-Forwarded-For',
        'X-Forwarded-Proto',
        'X-Forwarded-Unrecognized',
        'x-FoRwArDeD-host',
    ],
)
@pytest.mark.parametrize('value', ['', '127.0.0.1'])
def test_any_proxy_header_disables_local_actions(header: str, value: str) -> None:
    assert not is_same_machine(_request(headers={header: value}))


@pytest.mark.parametrize(
    'host',
    [
        'localhost',
        'LOCALHOST.',
        'localhost:8314',
        '127.0.0.1',
        '[::1]:8314',
        '192.168.2.4',
    ],
)
def test_literal_host_allows_local_actions(host: str) -> None:
    assert is_address_host(_request(headers={'Host': host}))


@pytest.mark.parametrize(
    'host',
    [
        'desk',
        'desk.local',
        'localhost..',
        'foreign@localhost',
        '127.0.0.1:bad',
        '[::1]bad',
    ],
)
def test_names_and_malformed_host_do_not_allow_local_actions(host: str) -> None:
    assert not is_address_host(_request(headers={'Host': host}))


def test_duplicate_host_disables_local_actions() -> None:
    assert not is_address_host(
        _request(headers=CIMultiDict([('Host', 'localhost'), ('Host', 'localhost')]))
    )


def test_open_requires_explicit_matching_origin_and_json() -> None:
    headers = {
        'Host': 'localhost:8314',
        'Origin': 'http://localhost:8314',
        'Content-Type': 'application/json',
    }
    assert is_open_allowed(_request(headers=headers))
    assert not is_open_allowed(_request('192.168.2.5', '192.168.2.4', headers))
    assert not is_open_allowed(
        _request(
            headers={key: value for key, value in headers.items() if key != 'Origin'}
        )
    )
    assert not is_open_allowed(
        _request(headers={**headers, 'Content-Type': 'text/plain'})
    )
    assert not is_open_allowed(_request(headers={**headers, 'Origin': 'null'}))
    assert not is_open_allowed(
        _request(
            headers={
                **headers,
                'Host': 'desk.local:8314',
                'Origin': 'http://desk.local:8314',
            }
        )
    )


def test_read_capabilities_allow_missing_origin_but_never_foreign_metadata() -> None:
    headers = {'Host': 'localhost:8314'}
    assert is_origin_allowed(_request(headers=headers))
    assert not is_origin_allowed(_request(headers=headers), required=True)
    assert is_origin_allowed(
        _request(headers={**headers, 'Origin': 'http://localhost:8314'}), required=True
    )
    assert not is_origin_allowed(
        _request(headers={**headers, 'Origin': 'http://foreign.example'})
    )
    assert not is_origin_allowed(
        _request(headers={**headers, 'Sec-Fetch-Site': 'cross-site'})
    )
    duplicated = CIMultiDict[str](
        [
            ('Host', 'localhost:8314'),
            ('Origin', 'http://localhost:8314'),
            ('Origin', 'http://localhost:8314'),
        ]
    )
    assert not is_origin_allowed(_request(headers=duplicated))


def test_unrecognized_transport_address_does_not_grant_local_actions() -> None:
    request = _request('192.168.2.4', None)
    assert not is_same_machine(request)
    request = make_mocked_request(
        'GET', '/', protocol=Mock(peername=None, transport=None), transport=None
    )
    assert not is_same_machine(request)
