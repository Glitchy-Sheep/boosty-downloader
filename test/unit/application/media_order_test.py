"""Retained positions preserve removal history separately from current body order."""

from __future__ import annotations

import pytest

from boosty_downloader.application._media_order import order_media_ids


@pytest.mark.parametrize(
    ('previous', 'current', 'expected'),
    [
        ([], [], []),
        ([], ['A', 'B', 'C'], ['A', 'B', 'C']),
        (['A', 'B', 'C'], ['A', 'B', 'C'], ['A', 'B', 'C']),
        (['A', 'B', 'C'], [], ['A', 'B', 'C']),
        (
            ['A', 'removed-1', 'B', 'removed-2', 'C'],
            ['C', 'B', 'A'],
            ['C', 'removed-1', 'B', 'removed-2', 'A'],
        ),
        (['B', 'A', 'C'], ['X', 'B', 'C', 'Y'], ['X', 'B', 'A', 'C', 'Y']),
        (
            ['B', 'A', 'C'],
            ['X', 'Y', 'C', 'Z', 'B', 'W'],
            ['X', 'Y', 'C', 'A', 'Z', 'B', 'W'],
        ),
        (['A', 'B'], ['X', 'Y'], ['A', 'B', 'X', 'Y']),
        (
            ['A', 'B'],
            ['X', 'B', 'X', 'A', 'B', 'Y', 'Y'],
            ['X', 'B', 'A', 'Y'],
        ),
    ],
    ids=[
        'empty',
        'first-run',
        'unchanged',
        'all-removed',
        'reorder-around-removed',
        'insert-and-append',
        'new-groups-around-reordered-anchors',
        'no-current-anchors',
        'repeated-body-references',
    ],
)
def test_current_order_preserves_removed_slots(
    previous: list[str],
    current: list[str],
    expected: list[str],
):
    assert order_media_ids(previous, current) == expected


def test_successive_removals_keep_distinct_author_histories():
    first = order_media_ids(['A', 'B', 'C'], ['B', 'C'])
    second = order_media_ids(['B', 'C', 'A'], ['B', 'C'])
    assert first == ['A', 'B', 'C']
    assert second == ['B', 'C', 'A']

    first = order_media_ids(first, ['B'])
    second = order_media_ids(second, ['B'])
    assert first == ['A', 'B', 'C']
    assert second == ['B', 'C', 'A']
    assert [media_id for media_id in first if media_id != 'B'] == ['A', 'C']
    assert [media_id for media_id in second if media_id != 'B'] == ['C', 'A']


def test_returning_piece_uses_an_existing_slot_and_can_move_again():
    removed = order_media_ids(['A', 'B', 'C', 'D'], ['B', 'D'])
    assert removed == ['A', 'B', 'C', 'D']

    returned = order_media_ids(removed, ['D', 'A', 'B'])
    assert returned == ['D', 'A', 'C', 'B']

    edited = order_media_ids(returned, ['X', 'B', 'A', 'Y', 'D'])
    assert edited == ['X', 'B', 'A', 'C', 'Y', 'D']
    assert order_media_ids(edited, ['X', 'B', 'A', 'Y', 'D']) == edited


def test_inputs_and_returned_inventory_have_independent_ownership():
    previous = ['B', 'A', 'C']
    current = ['X', 'B', 'C']
    ordered = order_media_ids(previous, current)

    assert previous == ['B', 'A', 'C']
    assert current == ['X', 'B', 'C']
    ordered.append('local edit')
    assert previous == ['B', 'A', 'C']
    assert current == ['X', 'B', 'C']
    assert order_media_ids(tuple(previous), tuple(current)) == ['X', 'B', 'A', 'C']
