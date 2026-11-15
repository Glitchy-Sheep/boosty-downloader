"""Run-scoped diagnostics: ordinary runs use a file, previews use the console."""

from __future__ import annotations

import importlib.metadata
import logging
import platform
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.logging import RichHandler

if TYPE_CHECKING:
    from collections.abc import Generator

DEBUG_LOG_FILENAME = 'boosty-downloader-debug.log'

# Only the application's two logger trees belong in diagnostic reports.
_LOGGER_NAMES = ('Boosty_Downloader', 'boosty_downloader')


class _DebugFileHandler(RichHandler):
    """Identify an active file diagnostic sink for error-reporting hints."""


def is_debug_enabled() -> bool:
    """Tell whether this run writes the debug log file."""
    return any(
        isinstance(handler, _DebugFileHandler)
        for handler in logging.getLogger(_LOGGER_NAMES[0]).handlers
    )


def _only_debug(record: logging.LogRecord) -> bool:
    """Ordinary console handlers already display INFO and higher levels."""
    return record.levelno == logging.DEBUG


@contextmanager
def _attach_handler(handler: RichHandler) -> Generator[None]:
    levels = {
        logging.getLogger(name): logging.getLogger(name).level for name in _LOGGER_NAMES
    }
    handler.setLevel(logging.DEBUG)
    try:
        for logger in levels:
            logger.setLevel(logging.DEBUG)
            logger.addHandler(handler)
        yield
    finally:
        for logger, level in levels.items():
            logger.removeHandler(handler)
            logger.setLevel(level)
        handler.close()


def _print_header(console: Console) -> None:
    version = importlib.metadata.version('boosty-downloader')
    console.print(
        f'boosty-downloader {version} | {platform.platform()} | '
        f'Python {platform.python_version()}'
    )
    console.print(f'argv: {" ".join(sys.argv)}')


def _make_handler(console: Console, *, read_only: bool) -> RichHandler:
    handler_type = RichHandler if read_only else _DebugFileHandler
    handler = handler_type(
        console=console,
        log_time_format='[%H:%M:%S]',
        markup=True,
        show_time=True,
        rich_tracebacks=True,
        show_path=False,
        show_level=True,
    )
    if read_only:
        handler.addFilter(_only_debug)
    return handler


@contextmanager
def debug_logging(*, enabled: bool, read_only: bool = False) -> Generator[None]:
    """Install diagnostics for one command and release its handlers and file."""
    if not enabled:
        yield
        return
    if read_only:
        console = Console(stderr=True)
        with _attach_handler(_make_handler(console, read_only=True)):
            _print_header(console)
            yield
        return
    with Path(DEBUG_LOG_FILENAME).open('w', encoding='utf-8') as stream:
        console = Console(file=stream, no_color=True, width=120)
        with _attach_handler(_make_handler(console, read_only=False)):
            _print_header(console)
            yield
