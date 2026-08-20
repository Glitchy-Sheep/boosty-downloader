"""Module contains loggers for different parts of the app"""

from boosty_downloader.infrastructure.loggers.base import (
    RichLogger,
    configure_stdout_encoding,
)

configure_stdout_encoding()

downloader_logger = RichLogger('Boosty_Downloader')
