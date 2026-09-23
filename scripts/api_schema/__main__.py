"""
Observed schema of the Boosty API: `build` writes it, `changes` diffs against it.

- `task api:schema -- <blog>...` writes docs/api/boosty-api.yaml.
- `task api:changes -- <blog>...` lists what the live API added since.

Both read one page of posts per blog plus the newest post through the
single-post endpoint and turn the answers into shapes. The account token
comes from `BOOSTY_TOKEN` in the environment, else `auth.auth_header` of
config.yaml, else ./.env; `--anonymous` sends none. Blog names stay in the
terminal: the files record shapes and counts only.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, cast

import rich
import typer
import yaml

from api_schema.live_api import (
    LiveApiError,
    fetch_listing_pages,
    fetch_single_post,
    find_account_token,
    open_api_session,
)
from api_schema.observed_shapes import ObservedObject, observe
from api_schema.openapi_document import ObservedAnswers, build_openapi_document, to_yaml
from api_schema.schema_changes import SchemaChange, find_changes
from api_schema.unread_keys import keys_unread_by_client

DEFAULT_OUTPUT = Path('docs/api/boosty-api.yaml')
DEFAULT_CONFIG = Path('config.yaml')
DEFAULT_CHANGES = Path('api-changes.json')
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
    token = None if anonymous else find_account_token(config)
    try:
        observation = asyncio.run(_observe_blog_answers(blogs, token, pages))
    except LiveApiError as error:
        rich.print(f'[red]{error}[/red]')
        raise typer.Exit(1) from error
    document = build_openapi_document(observation)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(to_yaml(document), encoding='utf-8')
    _print_summary(document, observation, output, with_token=token is not None)


@app.command()
def changes(
    blogs: Annotated[list[str], typer.Argument(help='Blog names to read')],
    pages: Annotated[int, typer.Option(help='Listing pages per blog')] = 1,
    output: Annotated[Path, typer.Option(help='Where to write the changes')] = (
        DEFAULT_CHANGES
    ),
    config: Annotated[
        Path, typer.Option(help='The app config whose auth.auth_header is the token')
    ] = DEFAULT_CONFIG,
    anonymous: Annotated[  # noqa: FBT002 - typer flag contract
        bool, typer.Option('--anonymous', help='Send no token at all')
    ] = False,
) -> None:
    """Write what the live answers have and the committed schema lacks, as JSON."""
    token = None if anonymous else find_account_token(config)
    try:
        observation = asyncio.run(_observe_blog_answers(blogs, token, pages))
    except LiveApiError as error:
        rich.print(f'[red]{error}[/red]')
        raise typer.Exit(1) from error
    committed = yaml.safe_load(DEFAULT_OUTPUT.read_text(encoding='utf-8'))
    found = find_changes(committed, build_openapi_document(observation))
    output.write_text(
        json.dumps([asdict(change) for change in found], indent=2) + '\n',
        encoding='utf-8',
    )
    _print_changes(found, output)


async def _observe_blog_answers(
    blogs: list[str], token: str | None, pages: int
) -> ObservedAnswers:
    """Read the blogs and keep only their shapes and counts."""
    page_shape = ObservedObject()
    post_shape = ObservedObject()
    posts = 0
    page_count = 0
    async with open_api_session(token) as session:
        for blog in blogs:
            answers = await fetch_listing_pages(session, blog, pages=pages)
            for page in answers:
                page_count += 1
                posts += _observe_listing_page(page, page_shape, post_shape)
            newest = _newest_post_id(answers[0]) if answers else None
            if newest is not None:
                observe(post_shape, await fetch_single_post(session, blog, newest))
                posts += 1
    return ObservedAnswers(
        page=page_shape,
        post=post_shape,
        captured_at=datetime.now(tz=timezone.utc).date().isoformat(),
        samples={'blogs': len(blogs), 'pages': page_count, 'posts': posts},
        unread_by_client=keys_unread_by_client(post_shape, page_shape),
    )


def _observe_listing_page(
    page: JsonDict, page_shape: ObservedObject, post_shape: ObservedObject
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


def _print_summary(
    document: JsonDict, observation: ObservedAnswers, output: Path, *, with_token: bool
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


def _print_changes(found: list[SchemaChange], output: Path) -> None:
    if not found:
        rich.print(f'[green]Nothing new against the schema[/green] ({output})')
        return
    rich.print(f'[yellow]{len(found)} changes against the schema[/yellow] ({output})')
    for change in found:
        rich.print(f'  {change.kind}: {change.where} {change.detail}')


if __name__ == '__main__':
    app()
