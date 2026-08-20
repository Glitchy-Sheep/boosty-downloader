"""Regression tests: a broken config.yaml must be reported, never replaced."""

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


def _write_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> Path:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / 'config.yaml'
    config.write_text(content, encoding='utf-8')
    return config


def test_broken_yaml_syntax_keeps_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old code replaced the user's config (and the token in it) with a sample."""
    config = _write_config(tmp_path, monkeypatch, BROKEN_YAML)

    with pytest.raises(SystemExit):
        init_config()

    assert config.read_text(encoding='utf-8') == BROKEN_YAML


def test_invalid_values_keep_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structure errors exit with a report, the file stays byte-identical."""
    config = _write_config(tmp_path, monkeypatch, BROKEN_STRUCTURE)

    with pytest.raises(SystemExit):
        init_config()

    assert config.read_text(encoding='utf-8') == BROKEN_STRUCTURE


def test_missing_config_creates_a_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First run: a sample appears so the user has something to fill in."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit):
        init_config()

    assert (tmp_path / 'config.yaml').exists()


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
        message = _broken_yaml_message(error)

    assert 'breaks at line 3, column 1' in message
    assert 'scalar' not in message
    assert 'block mapping' not in message
