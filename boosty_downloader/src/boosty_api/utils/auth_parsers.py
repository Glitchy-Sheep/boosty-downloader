"""Cookie and authorization parser module for raw-browser-data parsing"""

from http.cookies import SimpleCookie
from pathlib import Path

import aiohttp

from boosty_downloader.src.boosty_api.utils.oauth_manager import OAuthManager


async def parse_session_cookie(cookie_string: str) -> aiohttp.CookieJar:
    """Parse the session cookie and return a dictionary with auth data for aiohttp client."""
    if cookie_string.lower().startswith('cookie: '):
        cookie_string = cookie_string[8:].strip()

    cookie = SimpleCookie()
    cookie.load(cookie_string)

    jar = aiohttp.CookieJar()
    for key, morsel in cookie.items():
        jar.update_cookies({key: morsel.value})

    return jar


async def parse_auth_header(header: str, oauth_tokens_file: str = '') -> dict[str, str]:
    """Parse the authorization header and return a dictionary with auth data."""
    # If OAuth tokens file is specified, try to use OAuth tokens
    if oauth_tokens_file:
        oauth_manager = OAuthManager(Path(oauth_tokens_file))
        if oauth_manager.has_tokens():
            return {'Authorization': f'Bearer {oauth_manager.get_access_token()}'}
    
    # Fallback to provided header
    return {'Authorization': header}


def create_oauth_manager(oauth_tokens_file: str) -> OAuthManager:
    """Create OAuth manager for automatic token management"""
    return OAuthManager(Path(oauth_tokens_file))
