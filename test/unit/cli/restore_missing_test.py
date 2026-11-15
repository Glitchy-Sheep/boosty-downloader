"""The real CLI forwards restoration to each run's application dependencies."""

from __future__ import annotations

import io
import logging
from contextlib import asynccontextmanager
from enum import Enum, auto
from typing import TYPE_CHECKING, cast

import pytest
from rich.console import Console
from support.memory_post_store import MemoryPostStore
from typer.testing import CliRunner

from boosty_downloader.application.blog_overview import summarize_posts
from boosty_downloader.application.download_plan import build_download_plan
from boosty_downloader.application.post_retry import PostOutcome
from boosty_downloader.application.use_cases.download_all_posts import (
    DownloadAllPostUseCase,
)
from boosty_downloader.application.use_cases.download_post_by_id import (
    DownloadPostByIdUseCase,
)
from boosty_downloader.application.use_cases.plan_download import (
    DryRunReport,
    PlanDownloadUseCase,
)
from boosty_downloader.cli.commands import download as download_command
from boosty_downloader.cli.composition_root import App
from boosty_downloader.cli.console_progress_reporter import ConsoleProgressReporter
from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from aiohttp_retry import RetryClient

    from boosty_downloader.cli.composition_root import AppSettings
    from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIClient
    from boosty_downloader.infrastructure.loggers.base import RichLogger


class _Flow(Enum):
    bulk = auto()
    single = auto()
    preview = auto()


def _flow_args(flow: _Flow) -> list[str]:
    match flow:
        case _Flow.bulk:
            return []
        case _Flow.single:
            return ['--post-url', 'https://boosty.to/someone/posts/p1']
        case _Flow.preview:
            return ['--dry-run']


@pytest.fixture
def application(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    index_updates: list[bool] = []

    @asynccontextmanager
    async def open_test_app(
        settings: AppSettings,
        *,
        request_delay_seconds: float,
        logger: RichLogger,
        update_index: bool,
    ) -> AsyncGenerator[App, None]:
        del settings, request_delay_seconds, logger
        index_updates.append(update_index)
        yield App(
            api=cast('BoostyAPIClient', None),
            media_http=cast('RetryClient', None),
            post_store=MemoryPostStore(),
            reporter=ConsoleProgressReporter(
                console=Console(file=io.StringIO()),
                logger=logging.getLogger(__name__),
            ),
        )

    async def no_update_check(logger: RichLogger) -> None:
        del logger

    monkeypatch.setattr(download_command, 'open_app', open_test_app)
    monkeypatch.setattr(download_command, 'notify_about_updates', no_update_check)
    return index_updates


@pytest.mark.parametrize('flow', list(_Flow))
@pytest.mark.parametrize('restore_missing', [False, True], ids=['default', 'restore'])
def test_restore_missing_reaches_the_run_dependencies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flow: _Flow,
    application: list[bool],
    *,
    restore_missing: bool,
) -> None:
    observed: list[bool] = []

    async def bulk(use_case: DownloadAllPostUseCase) -> None:
        observed.append(use_case.context.restore_missing)

    async def single(use_case: DownloadPostByIdUseCase) -> PostOutcome:
        observed.append(use_case.context.restore_missing)
        return PostOutcome.downloaded

    async def preview(use_case: PlanDownloadUseCase) -> DryRunReport:
        observed.append(use_case.preparer.restore_missing)
        return DryRunReport(
            overview=summarize_posts(use_case.author_name, []),
            plan=build_download_plan([], preparer=use_case.preparer, filters=[]),
            problems=None,
        )

    monkeypatch.setattr(DownloadAllPostUseCase, 'execute', bulk)
    monkeypatch.setattr(DownloadPostByIdUseCase, 'execute', single)
    monkeypatch.setattr(PlanDownloadUseCase, 'execute', preview)
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'config.yaml').write_text(
        'auth:\n  cookie: "session=x"\n  auth_header: "Bearer x"\n', encoding='utf-8'
    )
    args = ['download', 'someone', *_flow_args(flow)]
    if restore_missing:
        args.append('--restore-missing')

    result = CliRunner().invoke(typer_app, args)

    assert result.exit_code == 0, result.output
    assert observed == [restore_missing]
    assert application == [flow is not _Flow.preview]
