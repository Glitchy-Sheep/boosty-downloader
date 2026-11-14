"""Deferred sources and forward links share one deduplicated refresh pass."""

from boosty_downloader.application.post_link_tracker import (
    PostLinkTracker,
    PostPageLocation,
)
from boosty_downloader.domain.library import PostIdentity

_SOURCE = PostPageLocation(PostIdentity('writer', 'source'), 'writer/source')
_FIRST = PostPageLocation(PostIdentity('writer', 'first'), 'writer/first')
_SECOND = PostPageLocation(PostIdentity('other', 'second'), 'other/second')


def test_only_published_targets_make_sources_ready_once() -> None:
    tracker = PostLinkTracker()
    tracker.record_render(_SOURCE, frozenset({_FIRST.identity, _SECOND.identity}))

    assert tracker.ready_sources() == ()
    tracker.record_render(_FIRST, frozenset())
    assert tracker.ready_sources() == (_SOURCE,)
    tracker.record_render(_SECOND, frozenset())
    assert tracker.ready_sources() == (_SOURCE,)
    tracker.record_render(_SOURCE, frozenset())
    assert tracker.ready_sources() == ()


def test_a_new_render_replaces_previous_links_and_source_location() -> None:
    tracker = PostLinkTracker()
    relocated = PostPageLocation(_SOURCE.identity, 'writer/moved-source')
    tracker.record_render(_SOURCE, frozenset({_FIRST.identity}))
    tracker.record_render(relocated, frozenset({_SECOND.identity}))
    tracker.record_render(_FIRST, frozenset())

    assert tracker.ready_sources() == ()
    tracker.record_render(_SECOND, frozenset())
    assert tracker.ready_sources() == (relocated,)


def test_target_matching_uses_author_and_full_post_id() -> None:
    tracker = PostLinkTracker()
    target = PostIdentity('writer', '12345678-full-target')
    tracker.record_render(_SOURCE, frozenset({target}))
    tracker.record_render(
        PostPageLocation(PostIdentity('other', target.post_id), 'other/target'),
        frozenset(),
    )
    tracker.record_render(
        PostPageLocation(PostIdentity('writer', '12345678-other'), 'writer/other'),
        frozenset(),
    )

    assert tracker.ready_sources() == ()
    exact = PostPageLocation(target, 'writer/target')
    tracker.record_render(exact, frozenset())
    assert tracker.ready_sources() == (_SOURCE,)


def test_a_first_self_link_becomes_ready_after_its_own_publication() -> None:
    tracker = PostLinkTracker()
    tracker.record_render(_SOURCE, frozenset({_SOURCE.identity}))

    assert tracker.ready_sources() == (_SOURCE,)
    tracker.record_render(_SOURCE, frozenset())
    assert tracker.ready_sources() == ()


def test_cyclic_sources_are_deduplicated_and_clear_independently() -> None:
    tracker = PostLinkTracker()
    tracker.record_render(_SOURCE, frozenset({_FIRST.identity}))
    tracker.record_render(_FIRST, frozenset({_SOURCE.identity}))

    assert tracker.ready_sources() == (_SOURCE, _FIRST)
    tracker.record_render(_SOURCE, frozenset())
    assert tracker.ready_sources() == (_FIRST,)
    tracker.record_render(_FIRST, frozenset())
    assert tracker.ready_sources() == ()


def test_deferred_source_is_ready_without_any_target() -> None:
    tracker = PostLinkTracker()
    tracker.defer_render(_SOURCE)

    assert tracker.ready_sources() == (_SOURCE,)
    assert tracker.ready_sources() == (_SOURCE,)


def test_deferring_a_target_does_not_publish_it() -> None:
    tracker = PostLinkTracker()
    tracker.record_render(_SOURCE, frozenset({_FIRST.identity}))
    tracker.defer_render(_FIRST)

    assert tracker.ready_sources() == (_FIRST,)
    tracker.record_render(_FIRST, frozenset())
    assert tracker.ready_sources() == (_SOURCE,)


def test_repeated_deferrals_keep_only_the_latest_source_location() -> None:
    tracker = PostLinkTracker()
    relocated = PostPageLocation(_SOURCE.identity, 'writer/moved-source')
    tracker.defer_render(_SOURCE)
    tracker.defer_render(_SOURCE)
    tracker.defer_render(relocated)

    assert tracker.ready_sources() == (relocated,)


def test_deferred_location_wins_when_forward_repairs_overlap() -> None:
    tracker = PostLinkTracker()
    relocated = PostPageLocation(_SOURCE.identity, 'writer/moved-source')
    tracker.record_render(_SOURCE, frozenset({_FIRST.identity}))
    tracker.record_render(_SECOND, frozenset({_FIRST.identity}))
    tracker.record_render(_FIRST, frozenset())
    tracker.defer_render(relocated)
    tracker.defer_render(_FIRST)

    assert tracker.ready_sources() == (relocated, _SECOND, _FIRST)


def test_successful_render_clears_deferral_and_keeps_new_unresolved_links() -> None:
    tracker = PostLinkTracker()
    tracker.defer_render(_SOURCE)
    tracker.record_render(_SOURCE, frozenset({_SECOND.identity}))

    assert tracker.ready_sources() == ()
    tracker.record_render(_SECOND, frozenset())
    assert tracker.ready_sources() == (_SOURCE,)
    tracker.record_render(_SOURCE, frozenset())
    assert tracker.ready_sources() == ()


def test_deferred_deduplication_preserves_author_and_full_post_id() -> None:
    tracker = PostLinkTracker()
    sources = (
        PostPageLocation(PostIdentity('writer', '12345678-first'), 'writer/first'),
        PostPageLocation(PostIdentity('other', '12345678-first'), 'other/first'),
        PostPageLocation(PostIdentity('writer', '12345678-other'), 'writer/other'),
    )
    for source in sources:
        tracker.defer_render(source)
        tracker.defer_render(source)

    assert tracker.ready_sources() == sources
