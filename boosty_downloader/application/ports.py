"""
Ports of the application layer: what the use cases need from the outside.

Implementations live in cli (console reporter) and infrastructure (SQLite
cache, failed downloads log). They match structurally, without importing
this module; conformance is checked where the app is put together.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from boosty_downloader.application.filtering import DownloadContentTypeFilter


class ProgressReporter(Protocol):
    """Progress bars and messages of a run, as the use cases see them."""

    def create_task(
        self, name: str, total: int | None = None, indent_level: int = 0
    ) -> UUID: ...

    def update_task(
        self,
        task_uuid: UUID,
        advance: int = 1,
        total: int | None = None,
        description: str | None = None,
    ) -> None: ...

    def complete_task(self, task_uuid: UUID) -> None: ...

    def info(self, message: str) -> None: ...

    def success(self, message: str) -> None: ...

    def warn(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...

    def notice(self, message: str) -> None: ...


class PostCache(Protocol):
    """Which parts of a post an earlier run already saved."""

    def has_post(self, post_uuid: str) -> bool: ...

    def get_post_missing_parts(
        self,
        post_uuid: str,
        updated_at: datetime,
        required: list[DownloadContentTypeFilter],
    ) -> list[DownloadContentTypeFilter]: ...

    def cache_post(
        self,
        post_uuid: str,
        updated_at: datetime,
        was_downloaded: list[DownloadContentTypeFilter],
    ) -> None: ...

    def commit(self) -> None: ...


class FailureLog(Protocol):
    """Where failed downloads are recorded for the user to act on later."""

    async def add_error(self, error_id: str, message: str) -> None: ...
