"""Track saved pages needing a link refresh after a successful run."""

from dataclasses import dataclass

from boosty_downloader.domain.library import PostIdentity


@dataclass(frozen=True, slots=True)
class PostPageLocation:
    """A full post identity and its owned library-relative folder."""

    identity: PostIdentity
    folder: str


@dataclass(frozen=True, slots=True)
class _PendingLinks:
    source: PostPageLocation
    targets: frozenset[PostIdentity]


class PostLinkTracker:
    """Keep successful page publications separate from storage and run statistics."""

    def __init__(self) -> None:
        self._published: set[PostIdentity] = set()
        self._pending: dict[PostIdentity, _PendingLinks] = {}
        self._deferred: dict[PostIdentity, PostPageLocation] = {}

    def defer_render(self, location: PostPageLocation) -> None:
        """Queue an otherwise cached source without marking its page as published."""
        self._deferred[location.identity] = location

    def record_render(
        self, location: PostPageLocation, unresolved: frozenset[PostIdentity]
    ) -> None:
        """Replace a source's references after its page and record are published."""
        self._published.add(location.identity)
        self._deferred.pop(location.identity, None)
        if unresolved:
            self._pending[location.identity] = _PendingLinks(location, unresolved)
        else:
            self._pending.pop(location.identity, None)

    def ready_sources(self) -> tuple[PostPageLocation, ...]:
        """Combine deferred sources and forward repairs once per full identity."""
        ready = {
            identity: pending.source
            for identity, pending in self._pending.items()
            if pending.targets & self._published
        }
        ready.update(self._deferred)
        return tuple(ready.values())
