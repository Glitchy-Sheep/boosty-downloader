"""Command failure reporting and diagnostic hints."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING

import typer
from aiohttp.client_exceptions import ClientConnectorDNSError, ClientError

from boosty_downloader.infrastructure.library.errors import (
    AmbiguousPostFolderError,
    InvalidPostRecordError,
)
from boosty_downloader.infrastructure.loggers import logger_instances
from boosty_downloader.infrastructure.loggers.debug_file import (
    DEBUG_LOG_FILENAME,
    is_debug_enabled,
)

if TYPE_CHECKING:
    from collections.abc import Generator

_log = logging.getLogger(__name__)


def point_at_the_debug_log(*, read_only: bool = False) -> None:
    """Close an error message with the way to a diagnosable report."""
    _log.debug('Full traceback of the error:', exc_info=True)
    if read_only:
        logger_instances.downloader_logger.info(
            'Dry-run writes no diagnostic file. Re-run with --debug and '
            'include the console diagnostics in the issue.'
        )
    elif is_debug_enabled():
        logger_instances.downloader_logger.info(
            f'Details written to {DEBUG_LOG_FILENAME} - attach it to the issue.'
        )
    else:
        logger_instances.downloader_logger.info(
            f'Re-run with --debug and attach {DEBUG_LOG_FILENAME} to a GitHub issue.'
        )


def report_network_error(error: ClientError, *, read_only: bool = False) -> None:
    """One readable message per network failure kind, then the debug pointer."""
    if isinstance(error, ClientConnectorDNSError):
        logger_instances.downloader_logger.error(
            f'DNS lookup failed for {error.host} - the system could not turn the name into an address.\n'
            'Your browser may still work: browsers often use their own DNS.\n'
            'Try a different DNS (1.1.1.1) or a VPN that covers all apps.'
        )
    else:
        logger_instances.downloader_logger.error(
            f'Network error while talking to Boosty: {type(error).__name__}: {error}'
        )
    point_at_the_debug_log(read_only=read_only)


@contextmanager
def report_command_errors(*, read_only: bool = False) -> Generator[None]:
    """Render expected failures while the command's diagnostic sink is open."""
    try:
        yield
    except ClientError as error:
        report_network_error(error, read_only=read_only)
        raise typer.Exit(1) from error
    except (InvalidPostRecordError, AmbiguousPostFolderError) as error:
        logger_instances.downloader_logger.error(f'Cannot read saved post: {error}')
        point_at_the_debug_log(read_only=read_only)
        raise typer.Exit(1) from error
    except Exception:
        _log.debug('Command failed:', exc_info=True)
        raise
