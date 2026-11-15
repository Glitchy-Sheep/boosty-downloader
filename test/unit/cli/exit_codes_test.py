"""Automation reads $? - a failed run must not report success."""

from __future__ import annotations

import pytest
from rich.text import Text
from sqlalchemy.exc import OperationalError

from boosty_downloader import main as main_module
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationTooManyFailuresError,
)
from boosty_downloader.infrastructure.boosty_api.core.client import (
    BoostyAPINoUsernameError,
    BoostyAPIUnauthorizedError,
)


def _raising_app(error: BaseException) -> object:
    def fake_app() -> None:
        raise error

    return fake_app


@pytest.mark.parametrize(
    'error',
    [
        BoostyAPINoUsernameError('nobody'),
        BoostyAPIUnauthorizedError(),
        ApplicationTooManyFailuresError(streak=5),
    ],
    ids=['no-username', 'unauthorized', 'too-many-failures'],
)
def test_handled_errors_exit_with_code_1(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    """Cron and shell scripts treated every failure as success before."""
    monkeypatch.setattr(main_module, 'typer_app', _raising_app(error))

    with pytest.raises(SystemExit) as exc_info:
        main_module.entry_point()

    assert exc_info.value.code == 1


def test_user_cancel_exits_with_sigint_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl+C is an interrupted run, not a success: 130 is the shell convention."""
    monkeypatch.setattr(
        main_module, 'typer_app', _raising_app(ApplicationCancelledError(post_uuid='p'))
    )

    with pytest.raises(SystemExit) as exc_info:
        main_module.entry_point()

    assert exc_info.value.code == 130


def test_clean_run_exits_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Success must stay exit 0 - the fix touches only the failure branches."""
    monkeypatch.setattr(main_module, 'typer_app', lambda: None)

    main_module.entry_point()


def test_index_failure_reports_reindex_and_preserves_literal_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reason = 'index[red]/index.db is unavailable'
    error = OperationalError(None, None, OSError(reason))
    messages: list[str] = []
    monkeypatch.setattr(main_module, 'typer_app', _raising_app(error))
    monkeypatch.setattr(
        main_module.logger_instances.downloader_logger, 'error', messages.append
    )

    with pytest.raises(SystemExit) as exc_info:
        main_module.entry_point()

    assert exc_info.value.code == 1
    message = Text.from_markup(' '.join(messages)).plain
    assert 'Library index error' in message
    assert reason in message
    assert 'reindex' in message
    assert 'Saved post records and media are preserved' in message
    assert 'clean-cache' not in message
