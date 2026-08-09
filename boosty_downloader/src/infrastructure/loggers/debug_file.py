"""
Debug log file: the details of a run, written for attaching to issues.

The console output never changes - the file carries what the screen
does not: a run header, every request, full tracebacks.
"""

from __future__ import annotations

import importlib.metadata
import logging
import platform
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

DEBUG_LOG_FILENAME = 'boosty-downloader-debug.log'

# The file handler listens to these two logger trees:
# the user-facing RichLogger and the package's module loggers.
# Third-party debug noise (asyncio, charset probes) stays out.
_LOGGER_NAMES = ('Boosty_Downloader', 'boosty_downloader')

_enabled = False


def is_debug_enabled() -> bool:
    """Tell whether this run writes the debug log file."""
    return _enabled


def enable_debug_file_log() -> Path:
    """Start writing DEBUG and above into ./boosty-downloader-debug.log."""
    global _enabled  # noqa: PLW0603 - single process-wide switch
    log_path = Path(DEBUG_LOG_FILENAME)
    file_console = Console(
        file=log_path.open('w', encoding='utf-8'),
        no_color=True,
        width=120,
    )
    handler = RichHandler(
        console=file_console,
        log_time_format='[%H:%M:%S]',
        markup=True,
        show_time=True,
        rich_tracebacks=True,
        show_path=False,
        show_level=True,
    )
    handler.setLevel(logging.DEBUG)
    for name in _LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

    version = importlib.metadata.version('boosty-downloader')
    file_console.print(
        f'boosty-downloader {version} | {platform.platform()} | '
        f'Python {platform.python_version()}'
    )
    file_console.print(f'argv: {" ".join(sys.argv)}')
    _enabled = True
    return log_path
