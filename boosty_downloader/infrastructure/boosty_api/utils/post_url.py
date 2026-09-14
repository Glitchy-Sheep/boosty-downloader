"""Boosty post url as the user pastes it, split into the creator name and the post id."""

from __future__ import annotations

from dataclasses import dataclass

from yarl import URL

_HOSTS = frozenset({'boosty.to', 'www.boosty.to'})


@dataclass(frozen=True, slots=True)
class PostRef:
    """The two parts of a post url the client asks the API with."""

    author_name: str
    post_id: str


class InvalidPostUrlError(ValueError):
    """The url is not a link to a Boosty post."""

    def __init__(self, url: str) -> None:
        super().__init__(
            f'{url!r} is not a Boosty post link. '
            'Expected https://boosty.to/<creator>/posts/<post id>'
        )


def parse_post_url(url: str) -> PostRef:
    """Split https://boosty.to/<creator>/posts/<post id>; query and trailing slash are ignored."""
    parsed = URL(url)
    segments = [part for part in parsed.parts if part not in ('', '/')]
    well_formed = (
        parsed.host in _HOSTS
        and len(segments) == 3  # noqa: PLR2004 - creator / posts / id
        and segments[1] == 'posts'
    )
    if not well_formed:
        raise InvalidPostUrlError(url)
    return PostRef(author_name=segments[0], post_id=segments[2])
