"""Configuration for the whole application"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

import yaml
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from boosty_downloader.infrastructure.loggers import logger_instances
from boosty_downloader.infrastructure.yaml_configuration.sample_config import (
    DEFAULT_YAML_CONFIG_VALUE,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class DownloadSettings(BaseModel):
    """Settings for the script downloading process"""

    target_directory: Path = Path('./boosty-downloads')
    cache_directory: Path | None = None


class AuthSettings(BaseModel):
    """Configuration for authentication (cookies and authorization headers)"""

    cookie: str = Field(default='', min_length=1)
    auth_header: str = Field(default='', min_length=1)


# Where the config lives unless the user points elsewhere: next to where
# the app is run from.
DEFAULT_CONFIG_PATH: Path = Path('config.yaml')

T = TypeVar('T')


class _YamlSettings(BaseSettings):
    """Settings read from the yaml config file."""

    model_config = SettingsConfigDict(
        yaml_file=DEFAULT_CONFIG_PATH,
        yaml_file_encoding='utf-8',
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            YamlConfigSettingsSource(settings_cls),
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
        )


class Config(_YamlSettings):
    """General script configuration with subsections"""

    auth: AuthSettings = AuthSettings()
    downloading_settings: DownloadSettings = DownloadSettings()


class DownloadPaths(_YamlSettings):
    """
    The folders section of the config alone.

    Commands that never talk to the API read this: credentials are not
    checked, so a config without them, or with stale ones, still works.
    """

    model_config = SettingsConfigDict(extra='ignore')

    downloading_settings: DownloadSettings = DownloadSettings()


# pydantic-settings binds the yaml file to the class, so the file the user
# chose gets a class of its own.
def _read_config(config_path: Path) -> Config:
    class _ConfigAt(Config):
        model_config = SettingsConfigDict(yaml_file=config_path)

    return _ConfigAt()


def _read_paths(config_path: Path) -> DownloadPaths:
    class _PathsAt(DownloadPaths):
        model_config = SettingsConfigDict(yaml_file=config_path)

    return _PathsAt()


def create_sample_config_file(config_path: Path) -> None:
    """Write the sample config for the user to fill in."""
    with config_path.open(mode='w', encoding='utf-8') as f:
        f.write(DEFAULT_YAML_CONFIG_VALUE)


def _hint_fix_or_recreate(config_path: Path) -> None:
    logger_instances.downloader_logger.info(
        'Fix the file by hand, or delete it - the next run creates a fresh sample.'
    )
    logger_instances.downloader_logger.info(
        f'Config location: {config_path.absolute()}'
    )


# Pydantic error types translated into words a config-editing user
# understands; anything unlisted falls back to a neutral phrase, so
# developer jargon never reaches the screen.
_HUMAN_MESSAGES = {
    'model_type': 'should be a section with its own settings inside (see the sample)',
    'extra_forbidden': 'unknown setting - check the spelling',
    'missing': 'this setting is required',
    'string_type': 'should be text (wrap it in quotes)',
    'path_type': 'should be a folder path',
}


def _human_message(error_type: str) -> str:
    return _HUMAN_MESSAGES.get(error_type, 'has an unexpected value')


def _report_invalid_values(error: ValidationError, config_path: Path) -> None:
    """Name every broken field in plain words so the user can fix the file."""
    logger_instances.downloader_logger.error(f'{config_path.name} has invalid values:')
    for detail in error.errors():
        path = '.'.join(str(part) for part in detail['loc'])
        logger_instances.downloader_logger.error(
            f'  - {path}: {_human_message(detail["type"])}'
        )
    _hint_fix_or_recreate(config_path)


def _broken_yaml_message(error: yaml.YAMLError, file_name: str = 'config.yaml') -> str:
    """One plain sentence with the exact spot, no parser jargon."""
    if isinstance(error, yaml.MarkedYAMLError) and error.problem_mark is not None:
        mark = error.problem_mark
        return (
            f'{file_name} is not valid YAML - '
            f'the file breaks at line {mark.line + 1}, column {mark.column + 1}'
        )
    return f'{file_name} is not valid YAML'


def _report_broken_yaml(error: yaml.YAMLError, config_path: Path) -> None:
    logger_instances.downloader_logger.error(
        _broken_yaml_message(error, config_path.name)
    )
    _hint_fix_or_recreate(config_path)


def _create_sample_and_exit(config_path: Path) -> None:
    """First run: leave a sample for the user to fill in, never a silent default."""
    logger_instances.downloader_logger.error("Config doesn't exist")
    try:
        create_sample_config_file(config_path)
    except FileNotFoundError:
        logger_instances.downloader_logger.error(
            f'Cannot create the config at {config_path.absolute()}: '
            'the folder does not exist'
        )
        sys.exit(1)
    logger_instances.downloader_logger.success(
        f'Created a sample config file at {config_path.absolute()}, please fill `auth_header` and `cookie` with yours before running the app',
    )
    sys.exit(1)


def _read_or_exit(read: Callable[[Path], T], config_path: Path) -> T:
    """Read the file; a broken one is reported and never overwritten."""
    try:
        return read(config_path)
    except ValidationError as error:
        _report_invalid_values(error, config_path)
        sys.exit(1)
    except yaml.YAMLError as error:
        _report_broken_yaml(error, config_path)
        sys.exit(1)


def init_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Config:
    """Load the whole config, credentials included; a missing file gets the sample."""
    if not config_path.exists():
        _create_sample_and_exit(config_path)
    return _read_or_exit(_read_config, config_path)


def read_download_settings(config_path: Path = DEFAULT_CONFIG_PATH) -> DownloadSettings:
    """
    Load the folders from the config, credentials not needed.

    Without a config file the defaults apply: a command that only touches
    local files must not leave a sample config behind.
    """
    if not config_path.exists():
        return DownloadSettings()
    return _read_or_exit(_read_paths, config_path).downloading_settings
