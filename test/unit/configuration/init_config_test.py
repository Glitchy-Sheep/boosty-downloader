"""Regression tests: a broken config file must be reported, never replaced."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from boosty_downloader.infrastructure.yaml_configuration.config import (
    _broken_yaml_message,
    _human_message,
    init_config,
)

if TYPE_CHECKING:
    from pathlib import Path

BROKEN_YAML = 'auth:\n  cookie: "unclosed\n'
BROKEN_STRUCTURE = 'auth: [1, 2, 3]\n'
VALID = 'auth:\n  cookie: "session=x"\n  auth_header: "Bearer x"\n'


def test_broken_yaml_syntax_keeps_the_file(tmp_path: Path) -> None:
    """The old code replaced the user's config (and the token in it) with a sample."""
    config = tmp_path / 'config.yaml'
    config.write_text(BROKEN_YAML, encoding='utf-8')

    with pytest.raises(SystemExit):
        init_config(config)

    assert config.read_text(encoding='utf-8') == BROKEN_YAML


def test_invalid_values_keep_the_file(tmp_path: Path) -> None:
    """Structure errors exit with a report, the file stays byte-identical."""
    config = tmp_path / 'config.yaml'
    config.write_text(BROKEN_STRUCTURE, encoding='utf-8')

    with pytest.raises(SystemExit):
        init_config(config)

    assert config.read_text(encoding='utf-8') == BROKEN_STRUCTURE


def test_missing_config_creates_a_sample(tmp_path: Path) -> None:
    """First run: a sample appears so the user has something to fill in."""
    config = tmp_path / 'boosty' / 'main.yaml'
    config.parent.mkdir()

    with pytest.raises(SystemExit):
        init_config(config)

    assert config.exists()


def test_missing_folder_is_an_error_not_a_traceback(tmp_path: Path) -> None:
    """A typo in --config must not end in a raw FileNotFoundError."""
    with pytest.raises(SystemExit):
        init_config(tmp_path / 'nope' / 'config.yaml')

    assert not (tmp_path / 'nope').exists()


def test_the_default_path_is_next_to_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without --config nothing changes: config.yaml is looked up where the app runs."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'config.yaml').write_text(VALID, encoding='utf-8')

    config = init_config()

    assert config.auth.cookie == 'session=x'


def test_a_config_is_read_from_the_given_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file named by the user wins over a config.yaml in the working directory."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'config.yaml').write_text(BROKEN_STRUCTURE, encoding='utf-8')
    elsewhere = tmp_path / 'elsewhere' / 'alt.yaml'
    elsewhere.parent.mkdir()
    elsewhere.write_text(VALID, encoding='utf-8')

    config = init_config(elsewhere)

    assert config.auth.auth_header == 'Bearer x'


def test_pydantic_jargon_never_reaches_the_user() -> None:
    """Unknown error types fall back to a neutral phrase instead of raw pydantic text."""
    assert _human_message('model_type') == (
        'should be a section with its own settings inside (see the sample)'
    )
    assert _human_message('some_future_pydantic_type') == 'has an unexpected value'


def test_yaml_parser_jargon_never_reaches_the_user() -> None:
    """The message carries the line and column, not the parser's inner monologue."""
    try:
        yaml.safe_load(BROKEN_YAML)
    except yaml.YAMLError as error:
        message = _broken_yaml_message(error, 'alt.yaml')

    assert message.startswith('alt.yaml is not valid YAML')
    assert 'breaks at line 3, column 1' in message
    assert 'scalar' not in message
    assert 'block mapping' not in message
