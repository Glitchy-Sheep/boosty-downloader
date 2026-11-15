"""Versioned author details and locked-post JSON without filesystem access."""

from collections.abc import Mapping
from json import loads
from typing import Annotated, Final, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ValidationError,
    model_validator,
)

from boosty_downloader.domain.stored_post import AuthorInfo, LockedPost
from boosty_downloader.infrastructure.library._author_validation import (
    AUTHOR_VALUE_CONFIG,
    author_validation_message,
    validate_author_fields,
    validate_locked_fields,
)
from boosty_downloader.infrastructure.library._record_validation import (
    require_identity,
    validate_temporal_text,
)
from boosty_downloader.infrastructure.library.errors import (
    InvalidAuthorRecordError,
    UnsupportedAuthorSchemaError,
)

AUTHOR_SCHEMA_VERSION: Final = 1
LOCKED_SCHEMA_VERSION: Final = 2


class _AuthorDocument(BaseModel):
    model_config = AUTHOR_VALUE_CONFIG

    schema_version: int
    author: Annotated[AuthorInfo, AfterValidator(validate_author_fields)]


class _LockedDocument(BaseModel):
    model_config = AUTHOR_VALUE_CONFIG

    schema_version: int
    author: str
    posts: dict[str, Annotated[LockedPost, AfterValidator(validate_locked_fields)]]

    @model_validator(mode='after')
    def validate_identities(self) -> '_LockedDocument':
        require_identity(self.author, 'author')
        for post_id, locked in self.posts.items():
            if locked.post.author != self.author:
                message = 'Locked post author must match the document author'
                raise ValueError(message)
            if locked.post.id != post_id:
                message = 'Locked post key must match the full post ID'
                raise ValueError(message)
        return self


def _read_document(
    data: bytes, supported_versions: tuple[int, ...]
) -> dict[str, object]:
    try:
        document: object = loads(data.decode('utf-8'))
    except (ValueError, RecursionError) as error:
        message = 'Invalid author record: expected UTF-8 JSON'
        raise InvalidAuthorRecordError(message) from error
    if not isinstance(document, dict):
        message = 'Invalid author record: expected a JSON object'
        raise InvalidAuthorRecordError(message)
    raw = cast('dict[str, object]', document)
    _check_schema_version(raw, supported_versions)
    return raw


def _check_schema_version(
    document: Mapping[str, object], supported_versions: tuple[int, ...]
) -> None:
    version = document.get('schema_version')
    if type(version) is not int:
        message = 'Invalid author record: schema_version must be an integer'
        raise InvalidAuthorRecordError(message)
    if version not in supported_versions:
        supported = ', '.join(map(str, supported_versions))
        message = (
            f'Unsupported author schema version: {version}; supported: {supported}'
        )
        raise UnsupportedAuthorSchemaError(message)


def _validate_v1_locked_fields(raw: Mapping[str, object]) -> None:
    posts = raw.get('posts')
    if raw['schema_version'] != 1 or not isinstance(posts, dict):
        return
    for locked in cast('dict[str, object]', posts).values():
        if isinstance(locked, dict) and 'teaser_thumbnail_path' in locked:
            message = (
                'teaser_thumbnail_path is not supported by locked schema version 1'
            )
            raise ValueError(message)


def _validate_locked_temporal_text(raw: Mapping[str, object]) -> None:
    posts = raw.get('posts')
    if not isinstance(posts, dict):
        return
    for locked in cast('dict[str, object]', posts).values():
        validate_temporal_text(locked)
        if isinstance(locked, dict):
            validate_temporal_text(cast('dict[str, object]', locked).get('post'))


def encode_author_record(info: AuthorInfo) -> bytes:
    """Encode complete author details as UTF-8 JSON without changing the input."""
    try:
        document = _AuthorDocument(schema_version=AUTHOR_SCHEMA_VERSION, author=info)
        return (document.model_dump_json(indent=2) + '\n').encode('utf-8')
    except ValidationError as error:
        raise InvalidAuthorRecordError(author_validation_message(error)) from None
    except (ValueError, TypeError, AttributeError) as error:
        message = 'Invalid author record: values cannot be encoded'
        raise InvalidAuthorRecordError(message) from error


def decode_author_record(data: bytes) -> AuthorInfo:
    """Decode a supported author record into an independent domain snapshot."""
    raw = _read_document(data, (AUTHOR_SCHEMA_VERSION,))
    try:
        validate_temporal_text(raw.get('author'))
        return _AuthorDocument.model_validate_json(data).author
    except ValidationError as error:
        raise InvalidAuthorRecordError(author_validation_message(error)) from None
    except ValueError as error:
        message = f'Invalid author record: {error}'
        raise InvalidAuthorRecordError(message) from error


def encode_locked_posts(author: str, posts: Mapping[str, LockedPost]) -> bytes:
    """Encode one author's observations, keyed by full post ID, without mutation."""
    try:
        document = _LockedDocument(
            schema_version=LOCKED_SCHEMA_VERSION, author=author, posts=dict(posts)
        )
        return (document.model_dump_json(indent=2) + '\n').encode('utf-8')
    except ValidationError as error:
        raise InvalidAuthorRecordError(author_validation_message(error)) from None
    except (ValueError, TypeError, AttributeError) as error:
        message = 'Invalid author record: values cannot be encoded'
        raise InvalidAuthorRecordError(message) from error


def decode_locked_posts(data: bytes, *, author: str) -> dict[str, LockedPost]:
    """Decode independent observations and check ownership, even for an empty map."""
    raw = _read_document(data, (1, LOCKED_SCHEMA_VERSION))
    try:
        _validate_v1_locked_fields(raw)
        _validate_locked_temporal_text(raw)
        document = _LockedDocument.model_validate_json(data)
    except ValidationError as error:
        raise InvalidAuthorRecordError(author_validation_message(error)) from None
    except ValueError as error:
        message = f'Invalid author record: {error}'
        raise InvalidAuthorRecordError(message) from error
    if document.author != author:
        message = 'Locked record belongs to another author'
        raise InvalidAuthorRecordError(message)
    return document.posts
