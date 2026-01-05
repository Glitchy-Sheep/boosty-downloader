"""CLI option definitions for Boosty Downloader."""

from pathlib import Path
from typing import Annotated

import typer

from boosty_downloader.src.application.filtering import (
    DownloadContentTypeFilter,
    VideoQualityOption,
)
from boosty_downloader.src.cli.help_panels import HelpPanels

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

CheckTotalCountOption = Annotated[
    bool,
    typer.Option(
        '--only-check-total',
        '-t',
        help='Check total count of accessible/inaccessible(+names) posts and exit, no download',
        rich_help_panel=HelpPanels.actions,
    ),
]

CleanCacheOption = Annotated[
    bool,
    typer.Option(
        '--clean-cache',
        '-c',
        help='Remove posts cache for selected username [italic]completely[/italic], use with caution',
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
