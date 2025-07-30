from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IntegrationTestConfig(BaseSettings):
    """
    Loads and validates integration test config from environment variables.
    """

    boosty_auth_token: str = Field(..., alias='BOOSTY_TOKEN')
    boosty_cookies: str = Field(..., alias='BOOSTY_COOKIES')

    boosty_available_post_url: str = Field(..., alias='BOOSTY_AVAILABLE_POST')
    boosty_unavailable_post_url: str = Field(..., alias='BOOSTY_UNAVAILABLE_POST')
    boosty_nonexistent_author: str = Field(..., alias='BOOSTY_NONEXISTENT_AUTHOR')
    boosty_existing_author: str = Field(..., alias='BOOSTY_EXISTING_AUTHOR')

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    def summary(self) -> str:
        """
        Prints all loaded config fields for debug purposes.
        """
        return str(self.model_dump())
