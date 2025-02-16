"""Boosty API client for accessing content."""

import aiohttp

from boosty_downloader.src.boosty_api.models.post.post import Post


class BoostyAPIClient:
    """
    Main client class for the Boosty API.

    It handles the connection and makes requests to the API.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    async def get_author_posts(self, author_name: str) -> list[Post]:
        endpoint = f'blog/{author_name}/post/'

        posts_raw = await self.session.get(endpoint)
        posts_data = await posts_raw.json()
        posts = posts_data['data']

        result: list[Post] = [Post.model_validate(post) for post in posts]
        return result
