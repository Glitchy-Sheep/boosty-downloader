"""Public post metadata shared by complete bodies and access observations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.domain.stored_post import PostMetadata

if TYPE_CHECKING:
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO


def map_post_metadata(post: PostDTO, author: str) -> PostMetadata:
    """Map the same public metadata for accessible and locked posts."""
    tier = post.subscription_level
    return PostMetadata(
        id=post.id,
        author=author,
        url=f'https://boosty.to/{author}/posts/{post.id}',
        title=post.title,
        created_at=post.created_at,
        updated_at=post.updated_at,
        published_at=post.publish_time,
        tags=[tag.title for tag in post.tags or []],
        tier=tier.name if tier else None,
        tier_price_rub=_rub_price(tier.currency_prices) if tier else None,
        post_price_rub=_rub_price(post.currency_prices),
        likes=post.count.likes if post.count else 0,
        comments=post.count.comments if post.count else 0,
        content_counters={
            item.type: item.count for item in post.content_counters or []
        },
    )


def _rub_price(prices: dict[str, float] | None) -> float | None:
    return prices.get('RUB') if prices is not None else None
