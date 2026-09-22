"""
`python -m api_schema build <blog>...`: write docs/api/boosty-api.yaml.

Run through `task api:schema -- <blog>...`. Reads one page of posts per blog
plus the newest post through the single-post endpoint, turns the answers
into shapes and writes them as OpenAPI 3.1. The account token comes from
`BOOSTY_TOKEN` in the environment, else `auth.auth_header` of config.yaml,
else ./.env; `--anonymous` sends none. Blog names stay in the terminal: the
file records counts only.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, cast

import rich
import typer

from api_schema.fetch import (
    FetchError,
    fetch_pages,
    fetch_post,
    load_token,
    open_session,
)
from api_schema.models import unread_by_client
from api_schema.openapi import Observation, build_document, to_yaml
from api_schema.shapes import ObjectShape, observe

DEFAULT_OUTPUT = Path('docs/api/boosty-api.yaml')
DEFAULT_CONFIG = Path('config.yaml')
JsonDict = dict[str, object]

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Observed schema of the Boosty API, built from live answers."""


@app.command()
def build(
    blogs: Annotated[list[str], typer.Argument(help='Blog names to read')],
    pages: Annotated[int, typer.Option(help='Listing pages per blog')] = 1,
    output: Annotated[Path, typer.Option(help='Where to write the document')] = (
        DEFAULT_OUTPUT
    ),
    config: Annotated[
        Path, typer.Option(help='The app config whose auth.auth_header is the token')
    ] = DEFAULT_CONFIG,
    anonymous: Annotated[  # noqa: FBT002 - typer flag contract
        bool, typer.Option('--anonymous', help='Send no token at all')
    ] = False,
) -> None:
    """Fetch the answers of the blogs and write the OpenAPI document."""
    token = None if anonymous else load_token(config)
    try:
        observation = asyncio.run(_observe_blogs(blogs, token, pages))
    except FetchError as error:
        rich.print(f'[red]{error}[/red]')
        raise typer.Exit(1) from error
    document = build_document(observation)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(to_yaml(document), encoding='utf-8')
    _report(document, observation, output, with_token=token is not None)


async def _observe_blogs(
    blogs: list[str], token: str | None, pages: int
) -> Observation:
    """Read the blogs and keep only their shapes and counts."""
    page_shape = ObjectShape()
    post_shape = ObjectShape()
    posts = 0
    page_count = 0
    async with open_session(token) as session:
        for blog in blogs:
            answers = await fetch_pages(session, blog, pages=pages)
            for page in answers:
                page_count += 1
                posts += _observe_page(page, page_shape, post_shape)
            newest = _newest_post_id(answers[0]) if answers else None
            if newest is not None:
                observe(post_shape, await fetch_post(session, blog, newest))
                posts += 1
    return Observation(
        page=page_shape,
        post=post_shape,
        captured_at=datetime.now(tz=timezone.utc).date().isoformat(),
        samples={'blogs': len(blogs), 'pages': page_count, 'posts': posts},
        unread_by_client=unread_by_client(post_shape, page_shape),
    )


def _observe_page(
    page: JsonDict, page_shape: ObjectShape, post_shape: ObjectShape
) -> int:
    """Count the page without its posts, then every post on its own."""
    data = cast('list[object]', page.get('data', []))
    observe(page_shape, {**page, 'data': []})
    for post in data:
        observe(post_shape, cast('JsonDict', post))
    return len(data)


def _newest_post_id(page: JsonDict) -> str | None:
    data = cast('list[JsonDict]', page.get('data', []))
    if not data:
        return None
    post_id = data[0].get('id')
    return post_id if isinstance(post_id, str) else None


def _report(
    document: JsonDict, observation: Observation, output: Path, *, with_token: bool
) -> None:
    components = cast('JsonDict', document['components'])
    schemas = cast('dict[str, JsonDict]', components['schemas'])
    chunks = sorted(name for name in schemas if name.startswith('Chunk'))
    mode = 'with the account token' if with_token else 'anonymous'
    rich.print(f'[green]Wrote {output}[/green] ({mode})')
    rich.print(f'Samples: {observation.samples}')
    rich.print(f'Chunk kinds: {", ".join(chunks) or "none"}')
    for name, keys in sorted(observation.unread_by_client.items()):
        rich.print(f'{name} keys the client ignores: {", ".join(keys)}')


if __name__ == '__main__':
    app()
