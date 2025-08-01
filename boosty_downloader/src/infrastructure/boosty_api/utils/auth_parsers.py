"""Cookie and authorization parser module for raw-browser-data parsing"""

from http.cookies import SimpleCookie

import aiohttp


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


async def parse_auth_header(header: str) -> dict[str, str]:
    """Parse the authorization header and return a dictionary with auth data."""
    return {'Authorization': header}
