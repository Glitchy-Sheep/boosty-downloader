"""The whole path a download takes before touching the disk.

Credentials and an author name go in; domain-ready posts come out.
Every stage failure names the place where the fix belongs.
"""

import warnings

from boosty_downloader.src.application.mappers.post_mapper import (
    map_post_dto_to_domain,
)
from boosty_downloader.src.infrastructure.boosty_api.core.client import (
    BoostyAPIClient,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
)
from boosty_downloader.src.infrastructure.boosty_api.models.unknown_content import (
    collect_unknown_content,
)
from integration.configuration import IntegrationTestConfig

pytest_plugins = [
    'integration.fixtures',
]

DTO_DIR = 'boosty_downloader/src/infrastructure/boosty_api/models/post/post_data_types/'


async def test_posts_page_parses_and_maps_to_domain(
    authorized_boosty_client: BoostyAPIClient, integration_config: IntegrationTestConfig
) -> None:
    """Fetch a live page, survive validation without losing posts, map all of them to domain."""
    # Stage 1: auth + author resolution + fetch.
    response = await authorized_boosty_client.get_author_posts(
        author_name=integration_config.boosty_existing_author, limit=10
    )
    assert response.posts, (
        f'No posts for "{integration_config.boosty_existing_author}" - '
        'BOOSTY_EXISTING_AUTHOR in ./.env must name an author with public posts'
    )

    # Stage 2: tolerant validation must keep every post of a public author.
    skipped_report = '\n'.join(
        f'  {post.post_id} "{post.title}": {len(post.errors)} validation errors'
        for post in response.skipped_posts
    )
    assert not response.skipped_posts, (
        f'Boosty serves structures the client cannot parse at all:\n{skipped_report}\n'
        f'Add the missing DTOs in {DTO_DIR}'
    )

    # Stage 3: every parsed post must map into a domain Post.
    # A mapper crash here fails the test with a traceback into the broken mapper.
    unknown_paths: set[str] = set()
    for post_dto in response.posts:
        map_post_dto_to_domain(
            post_dto, preferred_video_quality=BoostyOkVideoType.medium
        )
        unknown_paths |= {content.path for content in collect_unknown_content(post_dto)}

    # Stage 4: unknown content is tolerated by design, but never silent.
    if unknown_paths:
        warnings.warn(
            'New Boosty content tolerated as unknown: '
            f'{", ".join(sorted(unknown_paths))} - extend the DTOs in {DTO_DIR}',
            stacklevel=1,
        )
