"""Helpers for rendering network failures as short human messages."""

from __future__ import annotations

import logging

from aiohttp.client_exceptions import ClientConnectorDNSError, ClientError

from boosty_downloader.infrastructure.loggers import logger_instances
from boosty_downloader.infrastructure.loggers.debug_file import (
    DEBUG_LOG_FILENAME,
    is_debug_enabled,
)

_log = logging.getLogger(__name__)


def point_at_the_debug_log() -> None:
    """Close an error message with the way to a diagnosable report."""
    _log.debug('Full traceback of the error:', exc_info=True)
    if is_debug_enabled():
        logger_instances.downloader_logger.info(
            f'Details written to {DEBUG_LOG_FILENAME} - attach it to the issue.'
        )
    else:
        logger_instances.downloader_logger.info(
            f'Re-run with --debug and attach {DEBUG_LOG_FILENAME} to a GitHub issue.'
        )


def report_network_error(error: ClientError) -> None:
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
    point_at_the_debug_log()
