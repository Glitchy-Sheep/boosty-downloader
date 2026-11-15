"""Storage-neutral validation and independent author/access snapshots."""

from dataclasses import replace
from typing import Annotated, Final

from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError

from boosty_downloader.domain.stored_post import AuthorInfo, LockedPost
from boosty_downloader.infrastructure.library._record_validation import (
    as_utc,
    require_identity,
    require_nonnegative,
    validate_post_metadata,
    validate_relative_file_path,
)
from boosty_downloader.infrastructure.library._thumbnail_path import (
    validate_thumbnail_path,
)
from boosty_downloader.infrastructure.library.errors import InvalidAuthorRecordError

AUTHOR_VALUE_CONFIG: Final = ConfigDict(
    extra='forbid',
    hide_input_in_errors=True,
    strict=True,
    revalidate_instances='always',
    allow_inf_nan=False,
)


def validate_author_fields(info: AuthorInfo) -> AuthorInfo:
    """Validate portable references and normalize the observation clock."""
    require_identity(info.author, 'author')
    require_nonnegative(remote_post_count=info.remote_post_count)
    validate_relative_file_path(info.avatar_path, 'avatar_path')
    validate_relative_file_path(info.cover_path, 'cover_path')
    return replace(info, synced_at=as_utc(info.synced_at, 'synced_at'))


def validate_locked_fields(post: LockedPost) -> LockedPost:
    """Validate the locked overview and its author-relative image references."""
    validate_relative_file_path(post.teaser_path, 'teaser_path')
    validate_thumbnail_path(post.teaser_thumbnail_path, 'teaser_thumbnail_path')
    return replace(
        post,
        post=validate_post_metadata(post.post),
        synced_at=as_utc(post.synced_at, 'synced_at'),
    )


def author_validation_message(error: ValidationError) -> str:
    """Describe invalid fields without including private observation values."""
    problem = error.errors(
        include_input=False, include_context=False, include_url=False
    )[0]
    location = list(problem['loc'])
    if len(location) > 1 and location[0] == 'posts':
        location[1] = '<post>'
    field = '.'.join(str(part) for part in location) or 'record'
    return f'Invalid author record at {field}: {problem["msg"]}'


class _AuthorValue(BaseModel):
    model_config = AUTHOR_VALUE_CONFIG
    author: Annotated[AuthorInfo, AfterValidator(validate_author_fields)]


class _LockedValue(BaseModel):
    model_config = AUTHOR_VALUE_CONFIG
    locked: Annotated[LockedPost, AfterValidator(validate_locked_fields)]


def validate_author_snapshot(info: AuthorInfo) -> AuthorInfo:
    """Return one strictly validated author snapshot without storage envelopes."""
    try:
        return _AuthorValue(author=info).author
    except ValidationError as error:
        raise InvalidAuthorRecordError(author_validation_message(error)) from None


def validate_locked_snapshot(post: LockedPost) -> LockedPost:
    """Return a strictly validated observation with independent nested values."""
    try:
        return _LockedValue(locked=post).locked
    except ValidationError as error:
        raise InvalidAuthorRecordError(author_validation_message(error)) from None
