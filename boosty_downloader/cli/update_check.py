"""Update notice at the start of a run: a newer release on PyPI is worth knowing."""

from __future__ import annotations

import asyncio
import importlib.metadata
from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.update_checker.pypi_checker import (
    CheckFailed,
    NoUpdate,
    UpdateAvailable,
    check_for_updates,
)

if TYPE_CHECKING:
    from boosty_downloader.infrastructure.loggers.base import RichLogger


def _check_and_log_updates(logger: RichLogger) -> None:
    current_version = importlib.metadata.version('boosty-downloader')
    result = check_for_updates(current_version, 'boosty-downloader')
    match result:
        case UpdateAvailable():
            logger.warning(
                f'🔔 [bold green]Update available[/bold green]: {result.latest_version} (current: {result.current_version})'
            )
            logger.warning(
                'You can update with --> [bold]pip install -U boosty-downloader[/bold]'
            )
            logger.warning(
                'But first, please check the changelog for breaking changes\n'
            )
        case NoUpdate():
            logger.info('You are using the latest boosty-downloader version.\n')
        case CheckFailed():
            logger.error('Failed to check for updates, please check it manually.\n')


async def notify_about_updates(logger: RichLogger) -> None:
    """Check PyPI for a newer version and log the outcome."""
    # to_thread: the PyPI request is blocking; the event loop stays free.
    await asyncio.to_thread(_check_and_log_updates, logger)
