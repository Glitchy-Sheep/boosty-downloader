"""
Module with logger for failed downloads

The logger writes each failed download to a file in separate line
"""

from pathlib import Path

import aiofiles


class FailedDownloadsLogger:
    """Logger for failed downloads"""

    def __init__(self, file_path: Path) -> None:
        """
        Initialize the logger

        Args:
            file_path (Path): The path to the file to log failed downloads to

        """
        self.file_path = file_path

    async def _has_error(self, error: str) -> bool:
        """Read all errors from the file"""
        if not self.file_path.exists():
            return False

        async with aiofiles.open(self.file_path, encoding='utf-8') as file:
            async for line in file:
                if line.strip() == error:
                    return True

        return False

    async def _write_error(self, error: str) -> None:
        """Write an error to the file"""
        async with aiofiles.open(self.file_path, 'a', encoding='utf-8') as file:
            error = error.strip()
            await file.write(error + '\n')

    async def add_error(self, error: str) -> None:
        """Add an error to the log file if it doesn't exist yet"""
        if await self._has_error(error):
            return

        await self._write_error(error)
