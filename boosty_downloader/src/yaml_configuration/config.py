"""Configuration for the whole application"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from boosty_downloader.src.loggers.logger_instances import downloader_logger
from boosty_downloader.src.yaml_configuration.sample_config import (
    DEFAULT_YAML_CONFIG_VALUE,
)


class DownloadSettings(BaseModel):
    """Settings for the script downloading process"""

    target_directory: Path = Path('./boosty-downloads')


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


def init_config() -> Config:
    """Initialize the config file with a sample if it doesn't exist"""
    try:
        if not CONFIG_LOCATION.exists():
            create_sample_config_file()
            downloader_logger.error("Config doesn't exist")
            downloader_logger.success(
                f'Created a sample config file at {CONFIG_LOCATION.absolute()}, please fill `auth_header` and `cookie` with yours before running the app',
            )
            sys.exit(1)
        return Config()
    except ValidationError:
        # If can't be parsed correctly
        create_sample_config_file()
        downloader_logger.error('Config is invalid (could not be parsed)')
        downloader_logger.error(
            '[bold yellow]Make sure you fill `auth_header` and `cookie` with yours, they are required[/bold yellow]',
        )
        downloader_logger.success(
            f'Recreated it at [green bold]{CONFIG_LOCATION.absolute()}[/green bold]',
        )
        sys.exit(1)
