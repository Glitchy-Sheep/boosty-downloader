"""clean-cache must report honestly: nothing to clean vs cleaned, ask before removing, never touch a missing cache."""

from __future__ import annotations

from boosty_downloader.application.use_cases.clean_cache import (
    CleanCacheOutcome,
    CleanCacheUseCase,
)


class _FakeStorage:
    def __init__(self, *, present: bool) -> None:
        self._present = present
        self.removed = 0

    def exists(self) -> bool:
        return self._present

    def remove(self) -> None:
        self.removed += 1
        self._present = False


class _Answer:
    """A scripted answer to the confirmation question that counts how often it was asked."""

    def __init__(self, *, yes: bool) -> None:
        self._yes = yes
        self.asked = 0

    def __call__(self) -> bool:
        self.asked += 1
        return self._yes


def test_missing_cache_is_reported_and_left_alone():
    """The old command opened the database first, which created it and faked a success."""
    storage = _FakeStorage(present=False)
    answer = _Answer(yes=True)

    outcome = CleanCacheUseCase(storage, confirm=answer).execute()

    assert outcome is CleanCacheOutcome.nothing_to_clean
    assert storage.removed == 0
    assert answer.asked == 0, 'nothing to remove, nothing to ask about'


def test_existing_cache_is_removed_once_after_a_yes():
    storage = _FakeStorage(present=True)
    use_case = CleanCacheUseCase(storage, confirm=_Answer(yes=True))

    assert use_case.execute() is CleanCacheOutcome.cleaned
    assert storage.removed == 1
    # A second run finds nothing: the promise "fresh start" is kept, not repeated.
    assert use_case.execute() is CleanCacheOutcome.nothing_to_clean


def test_a_no_keeps_the_cache():
    """The cache is the only record of what was downloaded: a wrong key must not lose it."""
    storage = _FakeStorage(present=True)

    outcome = CleanCacheUseCase(storage, confirm=_Answer(yes=False)).execute()

    assert outcome is CleanCacheOutcome.cancelled
    assert storage.removed == 0
    assert storage.exists()
