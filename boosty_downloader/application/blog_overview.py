"""
A blog at a glance: how its posts unlock, what media they carry, when they were written.

Everything here comes from the post listing alone - no extra API calls.
Rendering the overview for the terminal is the CLI's job.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataAudioDTO,
    BoostyPostDataExternalVideoDTO,
    BoostyPostDataFileDTO,
    BoostyPostDataImageDTO,
    BoostyPostDataOkVideoDTO,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from boosty_downloader.infrastructure.boosty_api.models.post.base_post_data import (
        BasePostData,
    )
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO


@dataclass(frozen=True, slots=True)
class MediaCounts:
    """How many media pieces of each kind a set of posts carries."""

    images: int = 0
    files: int = 0
    boosty_videos: int = 0
    external_videos: int = 0
    audio: int = 0

    def __add__(self, other: MediaCounts) -> MediaCounts:
        """Sum the counts kind by kind."""
        return MediaCounts(
            images=self.images + other.images,
            files=self.files + other.files,
            boosty_videos=self.boosty_videos + other.boosty_videos,
            external_videos=self.external_videos + other.external_videos,
            audio=self.audio + other.audio,
        )


def count_media(chunks: Iterable[BasePostData]) -> MediaCounts:
    """Count the downloadable media among post chunks."""
    by_kind = Counter(type(chunk) for chunk in chunks)
    return MediaCounts(
        images=by_kind[BoostyPostDataImageDTO],
        files=by_kind[BoostyPostDataFileDTO],
        boosty_videos=by_kind[BoostyPostDataOkVideoDTO],
        external_videos=by_kind[BoostyPostDataExternalVideoDTO],
        audio=by_kind[BoostyPostDataAudioDTO],
    )


@dataclass(frozen=True, slots=True)
class AccessGroup:
    """Posts unlocked the same way: free, by a subscription tier, or bought one by one."""

    # Subscription tier name. None when no tier is required.
    tier: str | None
    # Tier price in rubles per month. 0 without a tier or for a free tier.
    tier_price: float
    # Price of buying one post in rubles, 0 when posts are not sold separately.
    post_price: float
    posts: int
    accessible: int


@dataclass(frozen=True, slots=True)
class UnlockCost:
    """
    What opening a set of posts takes: one subscription tier plus one-off purchases.

    Boosty tiers are nested - a higher tier opens every lower one - so one
    subscription to the most expensive tier covers all tier posts.
    """

    # The most expensive tier among the posts. None when no post needs one.
    tier: str | None
    # Rubles per month, 0 without a tier or for a free tier.
    tier_price: float
    # Posts sold one by one that no tier covers.
    one_off_posts: int
    # Rubles for all of them.
    one_off_total: float

    @property
    def is_free(self) -> bool:
        return self.tier is None and self.one_off_posts == 0


@dataclass(frozen=True, slots=True)
class BlogOverview:
    """Summary of an author's posts built from the listing."""

    author_name: str
    total_posts: int
    accessible_posts: int
    # Free posts first, then tiers by price, then posts sold one by one.
    access_groups: list[AccessGroup]
    # What every post of the blog costs to open, and what this account still lacks.
    full_access_cost: UnlockCost
    remaining_cost: UnlockCost
    # Media of accessible posts only: a locked post carries a teaser, not its content.
    media: MediaCounts
    first_post_at: datetime | None
    last_post_at: datetime | None
    # Titles of the posts this account cannot open, in listing order.
    locked_post_titles: tuple[str, ...]


def summarize_posts(author_name: str, posts: Iterable[PostDTO]) -> BlogOverview:
    """Build the overview of a post listing."""
    posts = list(posts)
    accessible = [post for post in posts if post.has_access]
    media = sum((count_media(post.data) for post in accessible), MediaCounts())
    created_at = [post.created_at for post in posts]
    groups = _group_by_access(posts)
    return BlogOverview(
        author_name=author_name,
        total_posts=len(posts),
        accessible_posts=len(accessible),
        access_groups=groups,
        full_access_cost=_unlock_cost(groups, locked_only=False),
        remaining_cost=_unlock_cost(groups, locked_only=True),
        media=media,
        first_post_at=min(created_at) if created_at else None,
        last_post_at=max(created_at) if created_at else None,
        locked_post_titles=tuple(post.title for post in posts if not post.has_access),
    )


# (tier name, tier price, post price): one key per way to unlock a post.
_AccessKey = tuple[str | None, float, float]


def _access_key(post: PostDTO) -> _AccessKey:
    tier = post.subscription_level
    post_price = _price_in_rub(post.currency_prices, fallback=post.price)
    if tier is None:
        return (None, 0, post_price)
    tier_price = _price_in_rub(tier.currency_prices, fallback=tier.price)
    return (tier.name, tier_price, post_price)


def _price_in_rub(
    currency_prices: dict[str, float] | None, *, fallback: float
) -> float:
    """
    Pick the RUB price out of the per-currency map.

    The API's bare price comes in the account's display currency, so two
    accounts would see the same tier priced differently; RUB is stable.
    """
    if currency_prices and 'RUB' in currency_prices:
        return currency_prices['RUB']
    return fallback


def _group_by_access(posts: Iterable[PostDTO]) -> list[AccessGroup]:
    totals: Counter[_AccessKey] = Counter()
    accessible: Counter[_AccessKey] = Counter()
    for post in posts:
        key = _access_key(post)
        totals[key] += 1
        accessible[key] += int(post.has_access)
    groups: list[AccessGroup] = []
    for key, posts_count in totals.items():
        tier, tier_price, post_price = key
        groups.append(
            AccessGroup(
                tier=tier,
                tier_price=tier_price,
                post_price=post_price,
                posts=posts_count,
                accessible=accessible[key],
            )
        )
    return sorted(groups, key=_display_order)


def _display_order(group: AccessGroup) -> tuple[int, float, float, str]:
    """Free first, then tiers by price, then posts sold one by one."""
    if group.tier is not None:
        return (1, group.tier_price, group.post_price, group.tier)
    is_free = group.post_price == 0
    return (0 if is_free else 2, 0, group.post_price, '')


def _unlock_cost(groups: Iterable[AccessGroup], *, locked_only: bool) -> UnlockCost:
    """Pick the top tier among the groups and sum every post sold one by one."""
    tier: str | None = None
    tier_price = 0.0
    one_off_posts = 0
    one_off_total = 0.0
    for group in groups:
        count = group.posts - group.accessible if locked_only else group.posts
        if count == 0:
            continue
        if group.tier is not None:
            if tier is None or group.tier_price > tier_price:
                tier, tier_price = group.tier, group.tier_price
        elif group.post_price > 0:
            one_off_posts += count
            one_off_total += count * group.post_price
    return UnlockCost(
        tier=tier,
        tier_price=tier_price,
        one_off_posts=one_off_posts,
        one_off_total=one_off_total,
    )
