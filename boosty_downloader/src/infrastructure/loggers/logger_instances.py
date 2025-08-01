"""Module contains loggers for different parts of the app"""

from pathlib import Path

from boosty_downloader.src.infrastructure.loggers.base import RichLogger
from boosty_downloader.src.infrastructure.loggers.failed_downloads_logger import FailedDownloadsLogger

downloader_logger = RichLogger('Boosty_Downloader')

failed_downloads_logger = FailedDownloadsLogger(
    file_path=Path('failed_downloads.txt'),
)
