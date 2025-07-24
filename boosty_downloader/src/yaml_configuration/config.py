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

    cookie: str = Field(default='')
    auth_header: str = Field(default='')
    # OAuth tokens file path (optional)
    oauth_tokens_file: str = Field(default='oauth_tokens.json')
    # OAuth token refresh cooldown in seconds (default: 1 hour)
    oauth_refresh_cooldown: int = Field(default=3600)


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
                f'Created a sample config file at {CONFIG_LOCATION.absolute()}',
            )
            downloader_logger.info(
                'You can either fill `auth_header` and `cookie` fields, or use OAuth tokens with: python -m boosty_downloader.oauth_setup setup-oauth',
            )
            sys.exit(1)

        config = Config()

        # Validate that we have at least one authentication method
        from pathlib import Path  # noqa: PLC0415

        oauth_file = Path(config.auth.oauth_tokens_file)
        has_oauth = oauth_file.exists()
        has_legacy_auth = bool(
            config.auth.cookie.strip() and config.auth.auth_header.strip(),
        )

        if not has_oauth and not has_legacy_auth:
            downloader_logger.error('No authentication method configured')
            downloader_logger.info('You can either:')
            downloader_logger.info(
                '1. Set up OAuth tokens: python -m boosty_downloader.oauth_setup setup-oauth',
            )
            downloader_logger.info(
                '2. Fill `auth_header` and `cookie` fields in config.yaml',
            )
            sys.exit(1)

        return config

    except ValidationError as e:  # type: ignore
        # If can't be parsed correctly
        create_sample_config_file()
        downloader_logger.error('Config is invalid (could not be parsed)')
        downloader_logger.error(f'Validation error: {e}')
        downloader_logger.success(
            f'Recreated config at [green bold]{CONFIG_LOCATION.absolute()}[/green bold]',
        )
        sys.exit(1)
