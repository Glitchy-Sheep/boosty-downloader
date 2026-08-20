"""
Progress reporting and logging utilities for console-based Boosty downloader interface.

Includes a ProgressReporter class for rich progress bars and logging.
"""

import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TimeElapsedColumn,
)


class ProgressReporter:
    """
    Provides progress bar management and rich logging for console-based interfaces using the Rich library.

    Tasks are identified by UUIDs and can be nested using `level` to visually indent sub-tasks.
    """

    def __init__(
        self,
        console: Console | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.console = console or Console()
        self.progress = Progress(
            SpinnerColumn(),
            '[progress.description]{task.description}',
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=self.console,
            refresh_per_second=29,
            transient=True,
        )
        self._logger = logger or self._create_default_logger()
        self._uuid_to_task_id: dict[uuid.UUID, TaskID] = {}
        self._uuid_to_level: dict[uuid.UUID, int] = {}
        self._uuid_to_name: dict[uuid.UUID, str] = {}

    def _create_default_logger(self) -> logging.Logger:
        logger = logging.getLogger('ProgressLogger')
        logger.setLevel(logging.INFO)
        logger.addHandler(
            RichHandler(
                console=self.console, show_time=True, markup=True, show_path=False
            )
        )
        return logger

    def _format_description(self, name: str, level: int) -> str:
        indent = '  ' * level
        max_length = 80
        available = max_length - len(indent)

        if len(name) > available:
            name = name[: available - 1] + '…'  # use ellipsis

        return f'{indent}{name}'

    def start(self) -> None:
        self.progress.start()

    def stop(self) -> None:
        self.progress.stop()

    def create_task(
        self, name: str, total: int | None = None, indent_level: int = 0
    ) -> uuid.UUID:
        task_id = self.progress.add_task(
            self._format_description(name, indent_level), total=total
        )
        task_uuid = uuid.uuid4()
        self._uuid_to_task_id[task_uuid] = task_id
        self._uuid_to_level[task_uuid] = indent_level
        self._uuid_to_name[task_uuid] = name
        return task_uuid

    def update_task(
        self,
        task_uuid: uuid.UUID,
        advance: int = 1,
        total: int | None = None,
        description: str | None = None,
    ) -> None:
        task_id = self._uuid_to_task_id.get(task_uuid)
        if task_id is not None and task_id in self.progress.task_ids:
            level = self._uuid_to_level.get(task_uuid, 0)
            base_name = description or self._uuid_to_name.get(task_uuid, '')
            formatted_description = self._format_description(base_name, level)
            self.progress.update(
                task_id,
                advance=advance,
                total=total,
                description=formatted_description,
            )

    def complete_task(self, task_uuid: uuid.UUID) -> None:
        task_id = self._uuid_to_task_id.get(task_uuid)
        if task_id is not None and task_id in self.progress.task_ids:
            total = self.progress.tasks[task_id].total
            self.progress.update(task_id, completed=total, visible=False)
            self._uuid_to_task_id.pop(task_uuid, None)
            self._uuid_to_level.pop(task_uuid, None)
            self._uuid_to_name.pop(task_uuid, None)

    def info(self, message: str) -> None:
        self._logger.info(message)

    def success(self, message: str) -> None:
        self._logger.info(f'[bold green]✔ {message}[/bold green]')

    def warn(self, message: str) -> None:
        self._logger.warning(f'[bold yellow]⚠ {message}[/bold yellow]')

    def error(self, message: str) -> None:
        self._logger.error(f'[bold red]✖ {message}[/bold red]')

    def notice(self, message: str) -> None:
        self.console.print(
            f'[bold yellow]NOTICE:[/bold yellow] {message}', highlight=False
        )


@asynccontextmanager
async def use_reporter(
    reporter: ProgressReporter,
) -> AsyncGenerator[ProgressReporter, None]:
    """Async context manager to start and stop a ProgressReporter instance."""
    try:
        reporter.start()
        yield reporter
    finally:
        reporter.stop()
