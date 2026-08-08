"""Render pydantic validation errors as short human-readable lines."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_core import ErrorDetails


def format_validation_errors(errors: Sequence[ErrorDetails]) -> list[str]:
    """
    Turn pydantic error details into lines like ``data[8].playerUrls[4].type: unknown value 'ondemand_dash'``.

    The path style matches collect_unknown_content, so users see the same
    addressing everywhere. Enum mismatches show the offending word instead
    of the full list of expected values.
    """
    return [_format_error(error) for error in errors]


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
