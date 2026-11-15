"""Versioned post JSON encoding and validation without filesystem access."""

from collections.abc import Mapping
from dataclasses import replace
from json import loads
from typing import Annotated, Final, cast

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
    validate_temporal_text,
)
from boosty_downloader.infrastructure.library.errors import (
    InvalidPostRecordError,
    UnsupportedPostSchemaError,
)

POST_SCHEMA_VERSION: Final = 1
_INVALID_UNION_TAG: Final = 'union_tag_invalid'


def _validate_sync(sync: PostSync) -> PostSync:
    require_nonnegative(page_template=sync.page_template)
    return replace(
        sync,
        first_downloaded_at=as_utc(sync.first_downloaded_at, 'first_downloaded_at'),
        synced_at=as_utc(sync.synced_at, 'synced_at'),
    )


def _validate_media_numbers(entry: MediaEntry) -> None:
    require_nonnegative(
        position=entry.position,
        size=entry.size,
        width=entry.width,
        height=entry.height,
    )
    if entry.duration is not None:
        require_nonnegative(duration=entry.duration.total_seconds())


def _validate_media_entry(entry: MediaEntry) -> MediaEntry:
    _validate_media_numbers(entry)
    validate_relative_file_path(entry.path, 'path')
    validate_relative_file_path(entry.preview_path, 'preview_path')
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


class _PostDocument(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        hide_input_in_errors=True,
        strict=True,
        revalidate_instances='always',
        allow_inf_nan=False,
        ser_json_timedelta='iso8601',
    )

    schema_version: int
    post: Annotated[PostMetadata, AfterValidator(validate_post_metadata)]
    sync: Annotated[PostSync, AfterValidator(_validate_sync)]
    blocks: list[JsonBlock]
    media: dict[str, Annotated[MediaEntry, AfterValidator(_validate_media_entry)]]

    @field_validator('media')
    @classmethod
    def validate_media_identities(
        cls, media: dict[str, MediaEntry]
    ) -> dict[str, MediaEntry]:
        for media_id, entry in media.items():
            kind, separator, identity = media_id.partition(':')
            if not separator or kind != entry.kind.value or not identity.strip():
                message = (
                    'Media identity must contain its kind and a nonempty source ID'
                )
                raise ValueError(message)
        return media

    @model_validator(mode='after')
    def validate_references(self) -> '_PostDocument':
        for block in self.blocks:
            if isinstance(block, JsonMediaBlock) and block.media_id not in self.media:
                message = 'A body media reference is missing from the media inventory'
                raise ValueError(message)
        return self


def _validation_message(error: ValidationError) -> str:
    problem = error.errors(
        include_input=False, include_context=False, include_url=False
    )[0]
    location = '.'.join(str(part) for part in problem['loc']) or 'record'
    message = problem['msg']
    if problem['type'] == _INVALID_UNION_TAG:
        message = 'Unknown content type tag'
    return f'Invalid post record at {location}: {message}'


def _read_json_object(data: bytes) -> dict[str, object]:
    try:
        document: object = loads(data.decode('utf-8'))
    except (ValueError, RecursionError) as error:
        message = 'Invalid post record: expected UTF-8 JSON'
        raise InvalidPostRecordError(message) from error
    if not isinstance(document, dict):
        message = 'Invalid post record: expected a JSON object'
        raise InvalidPostRecordError(message)
    return cast('dict[str, object]', document)


def _read_schema_version(document: Mapping[str, object]) -> int:
    version = document.get('schema_version')
    if type(version) is not int:
        message = 'Invalid post record: schema_version must be an integer'
        raise InvalidPostRecordError(message)
    return version


def _validate_document_temporal_text(document: Mapping[str, object]) -> None:
    validate_temporal_text(document.get('post'))
    validate_temporal_text(document.get('sync'))
    media = document.get('media')
    if isinstance(media, dict):
        entries = cast('dict[str, object]', media)
        for entry in entries.values():
            validate_temporal_text(entry)


def _decode_document(data: bytes, raw: Mapping[str, object]) -> _PostDocument:
    try:
        _validate_document_temporal_text(raw)
        return _PostDocument.model_validate_json(data)
    except ValidationError as error:
        raise InvalidPostRecordError(_validation_message(error)) from None
    except ValueError as error:
        message = f'Invalid post record: {error}'
        raise InvalidPostRecordError(message) from error


def encode_post_record(record: StoredPost) -> bytes:
    """Validate a record and encode version1 UTF-8 JSON without mutating it."""
    try:
        document = _PostDocument(
            schema_version=POST_SCHEMA_VERSION,
            post=record.post,
            sync=record.sync,
            blocks=encode_blocks(record.blocks),
            media=record.media,
        )
        return (document.model_dump_json(indent=2) + '\n').encode('utf-8')
    except ValidationError as error:
        raise InvalidPostRecordError(_validation_message(error)) from None
    except (ValueError, TypeError, AttributeError) as error:
        message = 'Invalid post record: values cannot be encoded'
        raise InvalidPostRecordError(message) from error


def decode_post_record(data: bytes) -> StoredPost:
    """Decode a supported record into an independent domain snapshot."""
    raw = _read_json_object(data)
    version = _read_schema_version(raw)
    if version != POST_SCHEMA_VERSION:
        message = f'Unsupported post schema version: {version}; supported: {POST_SCHEMA_VERSION}'
        raise UnsupportedPostSchemaError(message)
    document = _decode_document(data, raw)
    return StoredPost(
        post=document.post,
        sync=document.sync,
        blocks=decode_blocks(document.blocks),
        media=document.media,
    )
