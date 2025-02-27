"""Logger for the application."""

import io
import logging
import sys

from rich.logging import RichHandler

# Detect if running in a terminal
is_terminal = sys.stdout.isatty()

# Ensure proper UTF-8 handling in non-interactive environments
if not is_terminal and 'pytest' not in sys.modules:
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding='utf-8',
        line_buffering=True,
    )


class Logger:
    """Enhanced logger with Rich for colorful output while keeping severity levels."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

        # Avoid adding duplicate handlers
        handler = RichHandler(
            log_time_format='[%H:%M:%S]',
            markup=True,
            show_time=True,
            rich_tracebacks=True,
            show_path=False,
            show_level=False,
        )

        self._handler = handler
        self._log = logging.getLogger(prefix)
        self._log.setLevel(logging.DEBUG)
        self._log.addHandler(handler)
        self.console = self._handler.console
        self.logging_logger_obj = self._log

    def _log_message(
        self,
        level: int,
        msg: str,
        *,
        highlight: bool = True,
        tab_level: int = 0,
    ) -> None:
        if highlight:
            self._log.log(level, '\t' * tab_level + msg)
        else:
            self._handler.console.log('\t' * tab_level + msg, highlight=False)

    def info(self, msg: str, *, highlight: bool = True, tab_level: int = 0) -> None:
        prefix = f'[cyan]{self.prefix}[/cyan][blue].INFO 🔹[/blue]:'
        self._log_message(
            logging.INFO,
            f'{prefix} {msg}',
            highlight=highlight,
            tab_level=tab_level,
        )

    def success(self, msg: str, *, highlight: bool = True, tab_level: int = 0) -> None:
        prefix = f'[cyan]{self.prefix}[/cyan][green].SUCCESS ✔[/green]:'
        self._log_message(
            logging.INFO,
            f'{prefix} {msg}',
            highlight=highlight,
            tab_level=tab_level,
        )

    def error(self, msg: str, *, highlight: bool = True, tab_level: int = 0) -> None:
        prefix = f'[cyan]{self.prefix}[/cyan][bold red].ERROR ❌[/bold red]:'
        self._log_message(
            logging.ERROR,
            f'{prefix} {msg}',
            highlight=highlight,
            tab_level=tab_level,
        )

    def wait(self, msg: str, *, highlight: bool = True, tab_level: int = 0) -> None:
        prefix = f'[cyan]{self.prefix}[/cyan][yellow].WAIT ⏳[/yellow]:'
        self._log_message(
            logging.INFO,
            f'{prefix} {msg}',
            highlight=highlight,
            tab_level=tab_level,
        )

    def warning(self, msg: str, *, highlight: bool = True, tab_level: int = 0) -> None:
        prefix = f'[cyan]{self.prefix}[/cyan][bold yellow].WARNING ⚠ [/bold yellow]:'
        self._log_message(
            logging.WARNING,
            f'{prefix} {msg}',
            highlight=highlight,
            tab_level=tab_level,
        )


log = Logger(prefix='boosty_downloader')
