"""Configuration for the whole application"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from boosty_downloader.src.infrastructure.loggers import logger_instances
from boosty_downloader.src.infrastructure.yaml_configuration.sample_config import (
    DEFAULT_YAML_CONFIG_VALUE,
)


class DownloadSettings(BaseModel):
    """Settings for the script downloading process"""

    target_directory: Path = Path('./boosty-downloads')
    cache_directory: Path | None = None


class AuthSettings(BaseModel):
    """Configuration for authentication (cookies and authorization headers)"""

    cookie: str = Field(default='', min_length=1)
    auth_header: str = Field(default='', min_length=1)


CONFIG_LOCATION: Path = Path('config.yaml')


class Config(BaseSettings):
    """General script configuration with subsections"""

    model_config = SettingsConfigDict(
        yaml_file=CONFIG_LOCATION,
        yaml_file_encoding='utf-8',
    )

    auth: AuthSettings = AuthSettings()
    downloading_settings: DownloadSettings = DownloadSettings()

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


def create_sample_config_file() -> None:
    """Create a sample config file if it doesn't exist."""
    with CONFIG_LOCATION.open(mode='w') as f:
        f.write(DEFAULT_YAML_CONFIG_VALUE)


def _hint_fix_or_recreate() -> None:
    logger_instances.downloader_logger.info(
        'Fix the file by hand, or delete it - the next run creates a fresh sample.'
    )
    logger_instances.downloader_logger.info(
        f'Config location: {CONFIG_LOCATION.absolute()}'
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


def _report_invalid_values(error: ValidationError) -> None:
    """Name every broken field in plain words so the user can fix the file."""
    logger_instances.downloader_logger.error('config.yaml has invalid values:')
    for detail in error.errors():
        path = '.'.join(str(part) for part in detail['loc'])
        logger_instances.downloader_logger.error(
            f'  - {path}: {_human_message(detail["type"])}'
        )
    _hint_fix_or_recreate()


def _broken_yaml_message(error: yaml.YAMLError) -> str:
    """One plain sentence with the exact spot, no parser jargon."""
    if isinstance(error, yaml.MarkedYAMLError) and error.problem_mark is not None:
        mark = error.problem_mark
        return (
            'config.yaml is not valid YAML - '
            f'the file breaks at line {mark.line + 1}, column {mark.column + 1}'
        )
    return 'config.yaml is not valid YAML'


def _report_broken_yaml(error: yaml.YAMLError) -> None:
    logger_instances.downloader_logger.error(_broken_yaml_message(error))
    _hint_fix_or_recreate()


def init_config() -> Config:
    """Load config.yaml; a broken file is reported and never overwritten."""
    if not CONFIG_LOCATION.exists():
        create_sample_config_file()
        logger_instances.downloader_logger.error("Config doesn't exist")
        logger_instances.downloader_logger.success(
            f'Created a sample config file at {CONFIG_LOCATION.absolute()}, please fill `auth_header` and `cookie` with yours before running the app',
        )
        sys.exit(1)

    try:
        return Config()
    except ValidationError as error:
        _report_invalid_values(error)
        sys.exit(1)
    except yaml.YAMLError as error:
        _report_broken_yaml(error)
        sys.exit(1)
