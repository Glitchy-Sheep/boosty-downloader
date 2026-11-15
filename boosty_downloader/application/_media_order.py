"""Retained media inventory order across edits to a post's body."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def order_media_ids(previous: Sequence[str], current: Sequence[str]) -> list[str]:
    """
    Keep removed pieces in their slots while current pieces follow the body.

    Previous IDs are unique and already sorted by retained inventory position. Repeated current references use their first occurrence. New pieces precede their next existing current anchor; pieces without an anchor follow the retained inventory.
    """
    known_ids = set(previous)
    current_order = dict.fromkeys(current)
    remaining = iter(current_order)
    ordered: list[str] = []
    for previous_id in previous:
        if previous_id not in current_order:
            ordered.append(previous_id)
            continue
        for current_id in remaining:
            ordered.append(current_id)
            if current_id in known_ids:
                break
    ordered.extend(remaining)
    return ordered
