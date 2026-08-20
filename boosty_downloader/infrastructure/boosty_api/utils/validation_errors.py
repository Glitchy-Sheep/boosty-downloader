"""Render pydantic validation errors as short human-readable lines."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from collections.abc import Set as AbstractSet

    from pydantic_core import ErrorDetails

    from boosty_downloader.infrastructure.boosty_api.models.post.posts_request import (
        SkippedPost,
    )
    from boosty_downloader.infrastructure.boosty_api.models.unknown_content import (
        UnknownContent,
    )

GITHUB_ISSUES_URL = 'https://github.com/Glitchy-Sheep/boosty-downloader/issues'


def format_validation_errors(errors: Sequence[ErrorDetails]) -> list[str]:
    """
    Turn pydantic error details into lines like ``data[8].playerUrls[4].type: unknown value 'imaginary_dash'``.

    The path style matches collect_unknown_content, so users see the same
    addressing everywhere. Enum mismatches show the offending word instead
    of the full list of expected values.
    """
    return [_format_error(error) for error in errors]


def format_run_summary(
    skipped_posts: Sequence[SkippedPost],
    unknown_content: AbstractSet[UnknownContent],
    failed_posts: Sequence[str] = (),
) -> str | None:
    """
    Build the final block about everything this run skipped or didn't understand.

    Returns None when there is nothing to report, so clean runs stay silent.
    """
    if not skipped_posts and not unknown_content and not failed_posts:
        return None

    lines: list[str] = []
    if failed_posts:
        lines.append(
            f'Posts that failed to download ({len(failed_posts)}), '
            'details in failed_downloads.log:'
        )
        lines.extend(f'  - {item}' for item in failed_posts)
    if not skipped_posts and not unknown_content:
        return '\n'.join(lines)

    lines.append('Some content was not understood by this version of the downloader:')
    if skipped_posts:
        lines.append(f' Skipped posts ({len(skipped_posts)}):')
        for skipped in skipped_posts:
            lines.append(f'  - "{skipped.title}" (id {skipped.post_id})')
            lines.extend(
                f'     - {line}' for line in format_validation_errors(skipped.errors)
            )
    if unknown_content:
        lines.append(' Unknown content (downloaded around, not lost):')
        lines.extend(
            f'  - {item.path} = {item.raw!r}'
            for item in sorted(unknown_content, key=lambda u: (u.path, u.raw))
        )
    lines.append(
        f'Please report this at {GITHUB_ISSUES_URL} so the client can be updated.'
    )
    return '\n'.join(lines)


def format_skipped_post(skipped: SkippedPost) -> str:
    """One warning block for a post the client could not parse."""
    details = '\n'.join(
        f'   - {line}' for line in format_validation_errors(skipped.errors)
    )
    return (
        f'Skipped post "{skipped.title}" (id {skipped.post_id}) - '
        f'unexpected structure:\n{details}'
    )


def _format_error(error: ErrorDetails) -> str:
    path = _format_loc(error['loc'])
    if error['type'] == 'enum':
        return f'{path}: unknown value {error.get("input")!r}'
    return f'{path}: {error["msg"]}'


def _format_loc(loc: tuple[int | str, ...]) -> str:
    path = ''
    for part in loc:
        if isinstance(part, int):
            path += f'[{part}]'
        else:
            path = f'{path}.{part}' if path else part
    return path or '(root)'
