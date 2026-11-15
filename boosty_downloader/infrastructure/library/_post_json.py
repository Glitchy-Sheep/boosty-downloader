"""Versioned post JSON encoding and validation without filesystem access."""

from collections.abc import Mapping
from json import loads
from typing import Annotated, Final, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ValidationError,
    field_validator,
    model_validator,
)

from boosty_downloader.domain.stored_post import (
    MediaEntry,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library._post_json_blocks import (
    JsonBlock,
    decode_blocks,
    encode_blocks,
)
from boosty_downloader.infrastructure.library._record_validation import (
    validate_post_metadata,
    validate_temporal_text,
)
from boosty_downloader.infrastructure.library._stored_validation import (
    STORED_VALUE_CONFIG,
    validate_media_entry,
    validate_media_identities,
    validate_media_references,
    validate_post_sync,
    validation_message,
)
from boosty_downloader.infrastructure.library.errors import (
    InvalidPostRecordError,
    UnsupportedPostSchemaError,
)

POST_SCHEMA_VERSION: Final = 2
_SUPPORTED_POST_VERSIONS: Final = (1, POST_SCHEMA_VERSION)


class _PostDocument(BaseModel):
    model_config = STORED_VALUE_CONFIG

    schema_version: int
    post: Annotated[PostMetadata, AfterValidator(validate_post_metadata)]
    sync: Annotated[PostSync, AfterValidator(validate_post_sync)]
    blocks: list[JsonBlock]
    media: dict[str, Annotated[MediaEntry, AfterValidator(validate_media_entry)]]

    @field_validator('media')
    @classmethod
    def validate_media_identities(
        cls, media: dict[str, MediaEntry]
    ) -> dict[str, MediaEntry]:
        return validate_media_identities(media)

    @model_validator(mode='after')
    def validate_references(self) -> '_PostDocument':
        validate_media_references(self.blocks, self.media)
        return self


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


def _validate_v1_media_fields(raw: Mapping[str, object]) -> None:
    media = raw.get('media')
    if raw['schema_version'] != 1 or not isinstance(media, dict):
        return
    for entry in cast('dict[str, object]', media).values():
        if isinstance(entry, dict) and 'thumbnail_path' in entry:
            message = 'thumbnail_path is not supported by post schema version 1'
            raise ValueError(message)


def _decode_document(data: bytes, raw: Mapping[str, object]) -> _PostDocument:
    try:
        _validate_v1_media_fields(raw)
        _validate_document_temporal_text(raw)
        return _PostDocument.model_validate_json(data)
    except ValidationError as error:
        raise InvalidPostRecordError(validation_message(error)) from None
    except ValueError as error:
        message = f'Invalid post record: {error}'
        raise InvalidPostRecordError(message) from error


def encode_post_record(record: StoredPost) -> bytes:
    """Validate a record and encode version2 UTF-8 JSON without mutating it."""
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
        raise InvalidPostRecordError(validation_message(error)) from None
    except (ValueError, TypeError, AttributeError) as error:
        message = 'Invalid post record: values cannot be encoded'
        raise InvalidPostRecordError(message) from error


def decode_post_record(data: bytes) -> StoredPost:
    """Decode a supported record into an independent domain snapshot."""
    raw = _read_json_object(data)
    version = _read_schema_version(raw)
    if version not in _SUPPORTED_POST_VERSIONS:
        supported = ', '.join(map(str, _SUPPORTED_POST_VERSIONS))
        message = f'Unsupported post schema version: {version}; supported: {supported}'
        raise UnsupportedPostSchemaError(message)
    document = _decode_document(data, raw)
    return StoredPost(
        post=document.post,
        sync=document.sync,
        blocks=decode_blocks(document.blocks),
        media=document.media,
    )
