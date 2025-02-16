"""Logger for the application."""

import io
import logging
import sys

from rich.console import Console
from rich.logging import RichHandler

is_terminal = sys.stdout.isatty()
if not is_terminal and 'pytest' not in sys.modules:
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding='utf-8',
        line_buffering=True,
    )

_console = Console(log_path=False)

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler()
        if is_terminal
        else RichHandler(
            console=_console,
            show_path=False,
            markup=True,
        ),
    ],
)


class Logger:
    """Wrapper around the logging library with some extra features."""

    def __init__(self, prefix: str) -> None:
        self._log = logging.getLogger(__name__)
        self.console = _console
        self.prefix = prefix

    def info(
        self,
        msg: str,
        *,
        should_log: bool = True,
        highlight: bool = True,
    ) -> None:
        if should_log:
            self.console.log(f'[{self.prefix}] ℹ  {msg}', highlight=highlight)

    def success(
        self,
        msg: str,
        *,
        should_log: bool = True,
        highlight: bool = True,
    ) -> None:
        if should_log:
            self.console.log(f'[{self.prefix}] - ✔ {msg}', highlight=highlight)

    def error(
        self,
        msg: str,
        *,
        should_log: bool = True,
        highlight: bool = True,
    ) -> None:
        if should_log:
            self.console.log(f'[{self.prefix}] - ❌ {msg}', highlight=highlight)

    def wait(
        self,
        msg: str,
        *,
        should_log: bool = True,
        highlight: bool = True,
    ) -> None:
        if should_log:
            self.console.log(f'[{self.prefix}] - ⏳ {msg}', highlight=highlight)

    def skip_lines(self, count: int) -> None:
        self.console.print('\n' * count, end='')
