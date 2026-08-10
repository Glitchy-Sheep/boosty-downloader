"""Main entrypoint of the app."""

from __future__ import annotations

import typer
from aiohttp.client_exceptions import ClientError
from sqlalchemy.exc import DatabaseError, IntegrityError, OperationalError

from boosty_downloader.src.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationTooManyFailuresError,
)
from boosty_downloader.src.cli.cli_options import (
    DebugOption,  # noqa: TC001
    VersionOption,  # noqa: TC001
)
from boosty_downloader.src.cli.commands import (
    check,
    clean_cache,
    download,
    show_auth_script,
)
from boosty_downloader.src.cli.error_reporting import report_network_error
from boosty_downloader.src.infrastructure.boosty_api.core.client import (
    BoostyAPIInvalidUsernameError,
    BoostyAPINoUsernameError,
    BoostyAPIUnauthorizedError,
    BoostyAPIUnknownError,
    BoostyAPIValidationError,
)
from boosty_downloader.src.infrastructure.boosty_api.utils.validation_errors import (
    GITHUB_ISSUES_URL,
    format_validation_errors,
)
from boosty_downloader.src.infrastructure.loggers import logger_instances

typer_app = typer.Typer(
    add_completion=False,
    rich_markup_mode='rich',
    invoke_without_command=True,
)


@typer_app.callback()
def _app_callback(  # pyright: ignore[reportUnusedFunction]
    ctx: typer.Context,
    _version: VersionOption = False,  # noqa: FBT002 - typer flag contract
    _debug: DebugOption = False,  # noqa: FBT002 - typer flag contract
) -> None:
    """
    CLI tool to download Boosty posts by author username.

    Run [bold]boosty-downloader COMMAND --help[/bold] to see details about a specific command.
    """
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit


# Register all CLI commands
download.register(typer_app)
check.register(typer_app)
clean_cache.register(typer_app)
show_auth_script.register(typer_app)


def entry_point() -> None:
    """Run the CLI app with top-level error handling."""
    try:
        typer_app()
    except BoostyAPINoUsernameError as e:
        logger_instances.downloader_logger.error(
            f"Author '{e.username}' not found. "
            'Username is the blog name from the author page URL: boosty.to/<username>'
        )
    except BoostyAPIInvalidUsernameError as e:
        logger_instances.downloader_logger.error(
            f"'{e.username}' is not a valid username. "
            'Use the blog name from the author page URL (boosty.to/<username>), '
            'not an email'
        )
    except BoostyAPIUnauthorizedError:
        logger_instances.downloader_logger.error(
            'Unauthorized: Bad credentials, please relogin and update your config file'
        )
    except BoostyAPIUnknownError:
        logger_instances.downloader_logger.error(
            f'Unknown error occurred, please report this at GitHub issues of the project: {GITHUB_ISSUES_URL}'
        )
    except BoostyAPIValidationError as e:
        details = '\n'.join(
            f'  - {line}' for line in format_validation_errors(e.errors)
        )
        logger_instances.downloader_logger.error(
            'Boosty API returned unexpected structures, the client probably needs to be updated.\n'
            f'Please report this at GitHub issues of the project: {GITHUB_ISSUES_URL}\n'
            '\n'
            f'{details}'
        )
    except ApplicationCancelledError:
        logger_instances.downloader_logger.warning(
            'Download cancelled by user, see you later! 💘\n'
        )
    except ApplicationTooManyFailuresError as e:
        logger_instances.downloader_logger.error(
            f'Download stopped after {e.streak} failed posts in a row - '
            'fix the cause and run the command again to resume.'
        )
    except ClientError as e:
        report_network_error(e)
    except (
        OperationalError,
        DatabaseError,
        IntegrityError,
    ) as e:
        logger_instances.downloader_logger.error('⚠️  Cache Error!\n' + str(e))
        logger_instances.downloader_logger.warning(
            'Cache format may be outdated after application update.'
        )
        logger_instances.downloader_logger.info(
            '👉 You can clean outdated cache with the [bold]clean-cache[/bold] command'
        )
        logger_instances.downloader_logger.info(
            '👉 If this will still happen - please report it at GitHub issues:'
        )
        logger_instances.downloader_logger.info(f'👉 {GITHUB_ISSUES_URL}')


if __name__ == '__main__':
    entry_point()
