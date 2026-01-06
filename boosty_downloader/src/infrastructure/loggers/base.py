"""Logger for the application."""

import io
import logging
import sys
from dataclasses import dataclass
from typing import ClassVar

from rich.console import Console
from rich.logging import RichHandler


class RichLoggerError(Exception):
    """Raised when RichLogger encounters an error."""


def configure_stdout_encoding() -> None:
    """Ensure proper UTF-8 handling in non-interactive environments."""
    if not sys.stdout.isatty() and 'pytest' not in sys.modules:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer,
            encoding='utf-8',
            line_buffering=True,
        )


@dataclass(frozen=True, slots=True)
class _LogStyle:
    """Visual style configuration for a log level."""

    level: int
    color: str
    label: str
    emoji: str


class RichLogger:
    """Enhanced logger with Rich for colorful output while keeping severity levels."""

    _STYLES: ClassVar[dict[str, _LogStyle]] = {
        'debug': _LogStyle(logging.DEBUG, 'dim', 'DEBUG', '🔍'),
        'info': _LogStyle(logging.INFO, 'blue', 'INFO', '🔹'),
        'success': _LogStyle(logging.INFO, 'green', 'SUCCESS', '✔'),
        'wait': _LogStyle(logging.INFO, 'yellow', 'WAIT', '⏳'),
        'warning': _LogStyle(logging.WARNING, 'bold yellow', 'WARNING', '⚠'),
        'error': _LogStyle(logging.ERROR, 'bold red', 'ERROR', '❌'),
    }
    _initialized_loggers: ClassVar[set[str]] = set()

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._logger = logging.getLogger(prefix)

        if prefix not in self._initialized_loggers:
            self._logger.setLevel(logging.DEBUG)
            self._logger.addHandler(self._create_handler())
            self._initialized_loggers.add(prefix)

    @staticmethod
    def _create_handler() -> RichHandler:
        return RichHandler(
            log_time_format='[%H:%M:%S]',
            markup=True,
            show_time=True,
            rich_tracebacks=True,
            show_path=False,
            show_level=False,
        )

    def _log(
        self,
        style_name: str,
        msg: str,
        *,
        indent: int = 0,
        exc_info: bool = False,
    ) -> None:
        style = self._STYLES[style_name]
        prefix = f'[cyan]{self._prefix}[/cyan][{style.color}].{style.label} {style.emoji}[/{style.color}]:'
        indentation = '    ' * indent
        self._logger.log(style.level, f'{indentation}{prefix} {msg}', exc_info=exc_info)

    def debug(self, msg: str, *, indent: int = 0) -> None:
        self._log('debug', msg, indent=indent)

    def info(self, msg: str, *, indent: int = 0) -> None:
        self._log('info', msg, indent=indent)

    def success(self, msg: str, *, indent: int = 0) -> None:
        self._log('success', msg, indent=indent)

    def wait(self, msg: str, *, indent: int = 0) -> None:
        self._log('wait', msg, indent=indent)

    def warning(self, msg: str, *, indent: int = 0) -> None:
        self._log('warning', msg, indent=indent)

    def error(self, msg: str, *, indent: int = 0) -> None:
        self._log('error', msg, indent=indent)

    def exception(self, msg: str, *, indent: int = 0) -> None:
        """Log error with exception traceback. Call from within an except block."""
        self._log('error', msg, indent=indent, exc_info=True)

    @property
    def console(self) -> Console:
        """Access to the Rich console for advanced formatting."""
        for handler in self._logger.handlers:
            if isinstance(handler, RichHandler):
                return handler.console
        raise RichLoggerError

    @property
    def logging_logger_obj(self) -> logging.Logger:
        """Access to the underlying stdlib logger."""
        return self._logger
