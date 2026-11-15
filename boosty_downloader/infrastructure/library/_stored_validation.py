"""Storage-neutral validation and independent snapshots of canonical post values."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Annotated, Final

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

from boosty_downloader.domain.stored_post import (
    MediaEntry,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library._post_json_blocks import (
    JsonBlock,
    JsonMediaBlock,
    decode_blocks,
    encode_blocks,
)
from boosty_downloader.infrastructure.library._record_validation import (
    as_utc,
    optional_utc,
    require_nonnegative,
    validate_post_metadata,
    validate_relative_file_path,
)
from boosty_downloader.infrastructure.library._thumbnail_path import (
    validate_thumbnail_path,
)
from boosty_downloader.infrastructure.library.errors import InvalidPostRecordError

STORED_VALUE_CONFIG: Final = ConfigDict(
    extra='forbid',
    hide_input_in_errors=True,
    strict=True,
    revalidate_instances='always',
    allow_inf_nan=False,
    ser_json_timedelta='iso8601',
)


def validate_post_sync(sync: PostSync) -> PostSync:
    """Validate page revisions and normalize record clocks without mutating input."""
    require_nonnegative(page_template=sync.page_template)
    return replace(
        sync,
        first_downloaded_at=as_utc(sync.first_downloaded_at, 'first_downloaded_at'),
        synced_at=as_utc(sync.synced_at, 'synced_at'),
    )


def validate_media_entry(entry: MediaEntry) -> MediaEntry:
    """Validate file state, portable path bases and media history."""
    require_nonnegative(
        position=entry.position, size=entry.size, width=entry.width, height=entry.height
    )
    if entry.duration is not None:
        require_nonnegative(duration=entry.duration.total_seconds())
    validate_relative_file_path(entry.path, 'path')
    validate_relative_file_path(entry.preview_path, 'preview_path')
    validate_thumbnail_path(entry.thumbnail_path, 'thumbnail_path')
    if entry.status == MediaStatus.downloaded and (
        entry.path is None or entry.size is None
    ):
        message = 'Downloaded media must have a path and a recorded size'
        raise ValueError(message)
    return replace(
        entry,
        added_at=as_utc(entry.added_at, 'added_at'),
        removed_at=optional_utc(entry.removed_at, 'removed_at'),
    )


def validate_media_identities(media: dict[str, MediaEntry]) -> dict[str, MediaEntry]:
    """Require each post-local key to identify its declared media kind."""
    for media_id, entry in media.items():
        kind, separator, identity = media_id.partition(':')
        if not separator or kind != entry.kind.value or not identity.strip():
            message = 'Media identity must contain its kind and a nonempty source ID'
            raise ValueError(message)
    return media


def validate_media_references(
    blocks: Sequence[JsonBlock], media: Mapping[str, MediaEntry]
) -> None:
    """Require every body media reference to have a retained inventory entry."""
    for block in blocks:
        if isinstance(block, JsonMediaBlock) and block.media_id not in media:
            message = 'A body media reference is missing from the media inventory'
            raise ValueError(message)


def validation_message(error: ValidationError) -> str:
    """Describe a contract violation without including private post content."""
    problem = error.errors(
        include_input=False, include_context=False, include_url=False
    )[0]
    location = '.'.join(str(part) for part in problem['loc']) or 'record'
    message = problem['msg']
    if problem['type'] == 'union_tag_invalid':
        message = 'Unknown content type tag'
    return f'Invalid post record at {location}: {message}'


class _StoredPostValue(BaseModel):
    model_config = STORED_VALUE_CONFIG

    post: Annotated[PostMetadata, AfterValidator(validate_post_metadata)]
    sync: Annotated[PostSync, AfterValidator(validate_post_sync)]
    blocks: list[JsonBlock]
    media: dict[str, Annotated[MediaEntry, AfterValidator(validate_media_entry)]]

    @field_validator('media')
    @classmethod
    def validate_inventory(cls, media: dict[str, MediaEntry]) -> dict[str, MediaEntry]:
        return validate_media_identities(media)

    @model_validator(mode='after')
    def validate_references(self) -> '_StoredPostValue':
        validate_media_references(self.blocks, self.media)
        return self


def validate_stored_post(record: StoredPost) -> StoredPost:
    """Return a validated, detached record without any storage-format envelope."""
    try:
        value = _StoredPostValue(
            post=record.post,
            sync=record.sync,
            blocks=encode_blocks(record.blocks),
            media=record.media,
        )
    except ValidationError as error:
        raise InvalidPostRecordError(validation_message(error)) from None
    except (ValueError, TypeError, AttributeError) as error:
        message = 'Invalid post record: values cannot be encoded'
        raise InvalidPostRecordError(message) from error
    return StoredPost(value.post, value.sync, decode_blocks(value.blocks), value.media)
