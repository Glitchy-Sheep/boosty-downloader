"""Module contains loggers for different parts of the app"""

from pathlib import Path

from boosty_downloader.src.loggers.base import Logger
from boosty_downloader.src.loggers.failed_downloads_logger import FailedDownloadsLogger

downloader_logger = Logger('Boosty_Downloader')

failed_downloads_logger = FailedDownloadsLogger(
    file_path=Path('failed_downloads.txt'),
)
