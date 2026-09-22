"""CLI option definitions for Boosty Downloader."""

import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from boosty_downloader.application.filtering import (
    VideoQualityOption,
)
from boosty_downloader.cli.help_panels import HelpPanels
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.infrastructure.loggers.debug_file import (
    enable_debug_file_log,
)

UsernameArgument = Annotated[
    str,
    typer.Argument(
        metavar='USERNAME',
        help='Creator name: the part of the blog url after boosty.to/',
        show_default=False,
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


ShowPostsOption = Annotated[
    bool,
    typer.Option(
        '--posts',
        help='List every post under its tier, newest first',
        rich_help_panel=HelpPanels.actions,
    ),
]

DryRunOption = Annotated[
    bool,
    typer.Option(
        '--dry-run',
        help='Show what a download run would fetch and exit without downloading',
        rich_help_panel=HelpPanels.actions,
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

YesOption = Annotated[
    bool,
    typer.Option(
        '--yes',
        '-y',
        help='Do not ask for confirmation',
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

ConfigPathOption = Annotated[
    Path,
    typer.Option(
        '--config',
        help='Config file to use; by default config.yaml in the folder the app runs from',
        envvar='BOOSTY_DOWNLOADER_CONFIG',
        dir_okay=False,
        file_okay=True,
    ),
]


@dataclass(frozen=True, slots=True)
class GlobalOptions:
    """Options given before the command name; the app callback sets them."""

    config_path: Path


def global_options(ctx: typer.Context) -> GlobalOptions:
    """Read the global options of this run from the typer context."""
    options = ctx.obj
    if not isinstance(options, GlobalOptions):
        msg = 'global options are missing: the app callback did not run'
        raise TypeError(msg)
    return options
