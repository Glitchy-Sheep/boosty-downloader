"""CLI option definitions for Boosty Downloader."""

import importlib.metadata
from pathlib import Path
from typing import Annotated

import typer

from boosty_downloader.src.application.filtering import (
    DownloadContentTypeFilter,
    VideoQualityOption,
)
from boosty_downloader.src.cli.help_panels import HelpPanels
from boosty_downloader.src.infrastructure.loggers.debug_file import (
    enable_debug_file_log,
)

UsernameOption = Annotated[
    str,
    typer.Option(
        '--username',
        '-u',
        help='Username to download posts from.',
    ),
]

RequestDelaySecondsOption = Annotated[
    float,
    typer.Option(
        '--request-delay-seconds',
        '-d',
        help='Delay between requests to the API, in seconds',
        min=1,
        rich_help_panel=HelpPanels.network,
    ),
]


ContentTypeFilterOption = Annotated[
    list[DownloadContentTypeFilter] | None,
    typer.Option(
        '--content-type-filter',
        '-f',
        help='Choose what content you want to download\n\n(default: ALL SET)',
        metavar='Available options:\n- files\n- post_content\n- boosty_videos\n- external_videos\n- audio\n',
        show_default=False,
        rich_help_panel=HelpPanels.filtering,
    ),
]


PreferredVideoQualityOption = Annotated[
    VideoQualityOption,
    typer.Option(
        '--preferred-video-quality',
        '-q',
        help='Preferred video quality. If not available, the best quality will be used.',
        metavar='Available options:\n- smallest_size\n- low\n- medium\n- high\n- highest',
        rich_help_panel=HelpPanels.filtering,
    ),
]

PostUrlOption = Annotated[
    str | None,
    typer.Option(
        '--post-url',
        '-p',
        help='Download only the specified post if possible',
        metavar='URL',
        show_default=False,
        rich_help_panel=HelpPanels.actions,
    ),
]

DestinationDirectoryOption = Annotated[
    Path | None,
    typer.Option(
        '--destination-directory',
        '-o',
        help='Directory to save downloaded posts',
        dir_okay=True,
        file_okay=False,
        resolve_path=True,
        rich_help_panel=HelpPanels.actions,
        show_default=False,
    ),
]

CacheDirectoryOption = Annotated[
    Path | None,
    typer.Option(
        '--cache-dir',
        help='Custom directory for cache database (useful when downloading to network storage), cache dir will have subdirectory for each author',
        dir_okay=True,
        file_okay=False,
        resolve_path=True,
        rich_help_panel=HelpPanels.actions,
        show_default=False,
    ),
]


SkipAllFailuresOption = Annotated[
    bool,
    typer.Option(
        '--skip-all-failures',
        help='Skip failed posts without limit '
        'instead of stopping after 5 failures in a row',
        rich_help_panel=HelpPanels.actions,
    ),
]


def _print_version(value: bool) -> None:  # noqa: FBT001 - typer callback contract
    if value:
        typer.echo(importlib.metadata.version('boosty-downloader'))
        raise typer.Exit


def _enable_debug(value: bool) -> None:  # noqa: FBT001 - typer callback contract
    if value:
        enable_debug_file_log()


VersionOption = Annotated[
    bool,
    typer.Option(
        '--version',
        '-V',
        help='Show the version and exit',
        callback=_print_version,
        is_eager=True,
    ),
]

DebugOption = Annotated[
    bool,
    typer.Option(
        '--debug',
        help='Write a detailed log file for bug reports',
        callback=_enable_debug,
        is_eager=True,
    ),
]
