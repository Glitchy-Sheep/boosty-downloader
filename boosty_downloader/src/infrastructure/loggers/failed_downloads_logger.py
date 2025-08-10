"""
Deduplicating file logger for failed downloads.

Format: "[<id>]: <message>"; duplicates are suppressed by <id>.
The log file and its parent directory are created on demand; writes append.
"""

import re
from pathlib import Path

import aiofiles


class FailedDownloadsLogger:
    """
    Append-only deduplicating logger keyed by error id.

    Will write to a log file created on demand.
    Each error id is unique and will be written only once.
    """

    def __init__(self, log_file_path: Path) -> None:
        self.file_path = log_file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._seen_ids: set[str] = set()
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self.file_path.exists():
            self._loaded = True
            return

        pattern = re.compile(r'^\[(?P<id>[^\]]+)\]:')
        async with aiofiles.open(self.file_path, encoding='utf-8') as f:
            async for line in f:
                m = pattern.match(line.strip())
                if m:
                    self._seen_ids.add(m.group('id'))
        self._loaded = True

    async def _write_line(self, line: str) -> None:
        async with aiofiles.open(self.file_path, 'a', encoding='utf-8') as f:
            await f.write(line.rstrip() + '\n')

    async def add_error(self, error_id: str, message: str) -> None:
        """
        Add a failed download error to the log.

        If the error ID is already logged, the message will be suppressed.
        """
        error_id = error_id.strip()
        message = message.strip()

        await self._ensure_loaded()
        if error_id in self._seen_ids:
            return

        await self._write_line(f'[{error_id}]: {message}')
        self._seen_ids.add(error_id)
