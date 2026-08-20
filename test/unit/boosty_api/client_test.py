"""Regression tests for BoostyAPIClient error mapping (status checks before body parsing)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import pytest
from aiohttp import ContentTypeError

from boosty_downloader.infrastructure.boosty_api.core.client import (
    BoostyAPIClient,
    BoostyAPIInvalidUsernameError,
    BoostyAPINoPostError,
    BoostyAPINoUsernameError,
    BoostyAPIUnauthorizedError,
    BoostyAPIUnknownError,
    BoostyAPIValidationError,
)

if TYPE_CHECKING:
    from aiohttp import RequestInfo
    from aiohttp_retry import RetryClient


class _JsonMustNotBeCalledError(AssertionError):
    """Raised by the fake response when a test forbids body parsing."""


@dataclass
class _FakeResponse:
    """Prepared HTTP response: a status plus either a JSON body or a parse error."""

    status: int
    json_data: Any = None
    json_error: Exception | None = None

    async def json(self) -> object:
        if self.json_error is not None:
            raise self.json_error
        return self.json_data


class _FakeSession:
    """Stub of RetryClient: returns the one prepared response for any GET."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def get(self, *args: object, **kwargs: object) -> _FakeResponse:
        del args, kwargs  # the stub answers any request the same way
        return self._response


def _make_client(response: _FakeResponse) -> BoostyAPIClient:
    return BoostyAPIClient(session=cast('RetryClient', _FakeSession(response)))


VALID_EXTRA: Any = {'offset': '', 'isLast': True}


async def test_404_maps_to_no_username_error_without_parsing_body():
    client = _make_client(
        _FakeResponse(status=404, json_error=_JsonMustNotBeCalledError())
    )

    with pytest.raises(BoostyAPINoUsernameError) as exc_info:
        await client.get_author_posts('ghost_author', limit=1)

    assert exc_info.value.username == 'ghost_author'


async def test_401_maps_to_unauthorized_error_without_parsing_body():
    client = _make_client(
        _FakeResponse(status=401, json_error=_JsonMustNotBeCalledError())
    )

    with pytest.raises(BoostyAPIUnauthorizedError):
        await client.get_author_posts('any_author', limit=1)


async def test_400_maps_to_invalid_username_error_without_parsing_body():
    client = _make_client(
        _FakeResponse(status=400, json_error=_JsonMustNotBeCalledError())
    )

    with pytest.raises(BoostyAPIInvalidUsernameError) as exc_info:
        await client.get_author_posts('someone@gmail.com', limit=1)

    assert exc_info.value.username == 'someone@gmail.com'


async def test_unexpected_status_maps_to_unknown_error():
    client = _make_client(
        _FakeResponse(status=500, json_error=_JsonMustNotBeCalledError())
    )

    with pytest.raises(BoostyAPIUnknownError):
        await client.get_author_posts('any_author', limit=1)


@pytest.mark.parametrize(
    'parse_error',
    [
        ContentTypeError(cast('RequestInfo', None), ()),
        json.JSONDecodeError('Expecting value', '<html></html>', 0),
    ],
    ids=['wrong_content_type', 'broken_json_body'],
)
async def test_200_with_non_json_body_maps_to_unknown_error(parse_error: Exception):
    client = _make_client(_FakeResponse(status=200, json_error=parse_error))

    with pytest.raises(BoostyAPIUnknownError):
        await client.get_author_posts('any_author', limit=1)


async def test_200_with_valid_empty_page_returns_posts_response():
    client = _make_client(
        _FakeResponse(status=200, json_data={'data': [], 'extra': VALID_EXTRA})
    )

    response = await client.get_author_posts('any_author', limit=1)

    assert response.posts == []
    assert response.extra.is_last is True
    assert response.extra.offset == ''


VALID_POST: Any = {
    'id': 'p1',
    'title': 'ok post',
    'createdAt': 1700000000,
    'updatedAt': 1700000000,
    'hasAccess': True,
    'signedQuery': '',
    'data': [],
}


async def test_broken_post_is_skipped_and_page_survives():
    client = _make_client(
        _FakeResponse(
            status=200,
            json_data={
                'data': [VALID_POST, {'id': 'b1', 'title': 'broken'}],
                'extra': VALID_EXTRA,
            },
        )
    )

    response = await client.get_author_posts('any_author', limit=2)

    assert [p.id for p in response.posts] == ['p1']
    assert len(response.skipped_posts) == 1
    assert response.skipped_posts[0].post_id == 'b1'
    assert response.skipped_posts[0].title == 'broken'
    assert response.skipped_posts[0].errors


async def test_page_of_only_broken_posts_returns_empty_not_error():
    client = _make_client(
        _FakeResponse(
            status=200,
            json_data={'data': [{'nope': 1}, {'nope': 2}], 'extra': VALID_EXTRA},
        )
    )

    response = await client.get_author_posts('any_author', limit=2)

    assert response.posts == []
    assert len(response.skipped_posts) == 2


async def test_broken_pagination_still_fails_the_page():
    client = _make_client(
        _FakeResponse(
            status=200,
            json_data={'data': [VALID_POST], 'extra': {'nope': 1}},
        )
    )

    with pytest.raises(BoostyAPIValidationError):
        await client.get_author_posts('any_author', limit=1)


async def test_single_post_parses_into_dto():
    client = _make_client(_FakeResponse(status=200, json_data=VALID_POST))

    post = await client.get_single_post('any_author', 'p1')

    assert post.id == 'p1'
    assert post.title == 'ok post'


async def test_single_post_404_names_the_missing_post():
    """A silent None would make 'not found' look like a network problem."""
    client = _make_client(_FakeResponse(status=404, json_data={}))

    with pytest.raises(BoostyAPINoPostError, match=r'p1.*any_author'):
        await client.get_single_post('any_author', 'p1')


async def test_single_post_validation_error_carries_details():
    """One post has no page to survive on: broken parsing must say what broke."""
    client = _make_client(
        _FakeResponse(status=200, json_data={'id': 'b1', 'title': 'broken'})
    )

    with pytest.raises(BoostyAPIValidationError) as exc_info:
        await client.get_single_post('any_author', 'b1')

    assert exc_info.value.errors


async def test_single_post_401_raises_unauthorized():
    client = _make_client(_FakeResponse(status=401, json_data={}))

    with pytest.raises(BoostyAPIUnauthorizedError):
        await client.get_single_post('any_author', 'p1')
