"""
Progress reporting and logging utilities for console-based Boosty downloader interface.

Includes a ProgressReporter class for rich progress bars and logging, and a FakeDownloader for demonstration/testing.
"""

import asyncio
import logging
import secrets
import uuid
from collections.abc import AsyncGenerator, Sequence
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

from boosty_downloader.src.infrastructure.loggers.base import RichLogger


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

    def newline(self, count: int = 1) -> None:
        for _ in range(count):
            self.console.print()

    def headline_rule(self) -> None:
        self.console.rule()

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

    def log_list(self, title: str, items: Sequence[str]) -> None:
        self.console.print(f'[bold cyan]{title}[/bold cyan]:')
        for item in items:
            self.console.print(f' • {item}')


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


# ------------------------------------------------------------------------------
# Usage example: run it as a script to see how it works:
# poetry run boosty_downloader .../console_progress_reporter.py

if __name__ == '__main__':
    import asyncio

    class FakeDownloader:
        """Just Stupid faker"""

        def __init__(self, reporter: ProgressReporter) -> None:
            self.reporter = reporter

        async def iterate_pages(
            self, total_pages: int = 3, posts_per_page: int = 5
        ) -> AsyncGenerator[list[str], None]:
            """Simulate stuff"""
            for page_num in range(1, total_pages + 1):
                await asyncio.sleep(0.5)
                posts = [
                    f'post_{(page_num - 1) * posts_per_page + i + 1:02}'
                    for i in range(posts_per_page)
                ]
                yield posts

        async def download_file(self, task_name: str, size_kb: int) -> None:
            """Simulate downloading a file of size size_kb KB with progress"""
            chunk_size = 50
            total_chunks = (size_kb + chunk_size - 1) // chunk_size
            download_task_id = self.reporter.create_task(task_name, total=total_chunks)

            for chunk in range(total_chunks):
                # Simulate delay proportional to chunk size
                await asyncio.sleep(secrets.randbelow(11) / 100 + 0.05)
                self.reporter.update_task(
                    download_task_id,
                    advance=1,
                    description=f'{task_name} [{min((chunk + 1) * chunk_size, size_kb)} KB / {size_kb} KB]',
                )
            self.reporter.complete_task(download_task_id)

        async def download_all_posts(self, username: str) -> None:
            """Simulate downloading all posts for a user with progress reporting"""
            self.reporter.notice(f'Starting download for user: {username}')
            self.reporter.headline_rule()

            total_posts = None
            download_task_id = self.reporter.create_task('posts', total=total_posts)

            downloaded_posts = 0

            async for posts in self.iterate_pages():
                self.reporter.info(f'Loaded new page with {len(posts)} posts')

                for post_title in posts:
                    self.reporter.info(f'Processing post: {post_title}')

                    if secrets.randbelow(10) == 0:
                        self.reporter.warn(f'Skipping inaccessible post: {post_title}')
                        self.reporter.update_task(download_task_id, advance=1)
                        continue

                    files = {
                        'image_1': secrets.randbelow(201) + 100,  # 100-300 KB
                        'video_1': secrets.randbelow(1501) + 1000,  # 1-2.5 MB
                        'attachment_1': secrets.randbelow(301) + 200,  # 200-500 KB
                    }

                    for fname, size_kb in files.items():
                        task_name = f'{post_title}::{fname}'
                        await self.download_file(task_name, size_kb)
                        self.reporter.success(f'Finished {fname} of {post_title}')

                    downloaded_posts += 1
                    self.reporter.update_task(download_task_id, advance=1)

                self.reporter.headline_rule()

            self.reporter.success(f'✅ Finished downloading {downloaded_posts} posts.')

    async def main() -> None:
        """Run a demonstration of the FakeDownloader with progress reporting."""
        logger = RichLogger('dumb')

        reporter = ProgressReporter(
            logger=logger.logging_logger_obj,
            console=logger.console,
        )
        async with use_reporter(reporter):
            downloader = FakeDownloader(reporter)
            await downloader.download_all_posts('demo_user')

    asyncio.run(main())
