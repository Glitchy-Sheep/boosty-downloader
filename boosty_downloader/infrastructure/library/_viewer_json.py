"""Versioned user viewing marks without filesystem access."""

from collections.abc import Mapping
from dataclasses import replace
from json import loads
from typing import Annotated, Final, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    ValidationError,
    model_validator,
)

from boosty_downloader.domain.library_marks import PostMarks
from boosty_downloader.infrastructure.library._record_validation import (
    optional_utc,
    require_identity,
    require_nonnegative,
    validate_temporal_text,
)
from boosty_downloader.infrastructure.library.errors import (
    InvalidViewerRecordError,
    UnsupportedViewerSchemaError,
)

VIEWER_SCHEMA_VERSION: Final = 1


def _validate_marks(marks: PostMarks) -> PostMarks:
    for media_id, position in marks.positions.items():
        require_identity(media_id, 'media_id')
        require_nonnegative(seconds=position.seconds)
    return replace(
        marks,
        seen_at=optional_utc(marks.seen_at, 'seen_at'),
        positions={
            media_id: replace(
                position,
                finished_at=optional_utc(position.finished_at, 'finished_at'),
            )
            for media_id, position in marks.positions.items()
        },
    )


class _ViewerDocument(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        hide_input_in_errors=True,
        strict=True,
        revalidate_instances='always',
        allow_inf_nan=False,
    )

    schema_version: int
    author: str
    post_id: str
    marks: Annotated[PostMarks, AfterValidator(_validate_marks)]

    @model_validator(mode='after')
    def validate_identities(self) -> '_ViewerDocument':
        require_identity(self.author, 'author')
        require_identity(self.post_id, 'post_id')
        return self


def _validation_message(error: ValidationError) -> str:
    problem = error.errors(
        include_input=False, include_context=False, include_url=False
    )[0]
    location = list(problem['loc'])
    match location:
        case ['marks', 'positions', _, *nested]:
            location = ['marks', 'positions', '<media>', *nested]
        case _:
            pass
    field = '.'.join(str(part) for part in location) or 'record'
    return f'Invalid viewer record at {field}: {problem["msg"]}'


def _read_document(data: bytes) -> dict[str, object]:
    try:
        document: object = loads(data.decode('utf-8'))
    except (ValueError, RecursionError) as error:
        message = 'Invalid viewer record: expected UTF-8 JSON'
        raise InvalidViewerRecordError(message) from error
    if not isinstance(document, dict):
        message = 'Invalid viewer record: expected a JSON object'
        raise InvalidViewerRecordError(message)
    raw = cast('dict[str, object]', document)
    _check_schema_version(raw)
    return raw


def _check_schema_version(document: Mapping[str, object]) -> None:
    version = document.get('schema_version')
    if type(version) is not int:
        message = 'Invalid viewer record: schema_version must be an integer'
        raise InvalidViewerRecordError(message)
    if version != VIEWER_SCHEMA_VERSION:
        message = (
            f'Unsupported viewer schema version: {version}; '
            f'supported: {VIEWER_SCHEMA_VERSION}'
        )
        raise UnsupportedViewerSchemaError(message)


def _validate_temporal_text(raw: Mapping[str, object]) -> None:
    marks = raw.get('marks')
    validate_temporal_text(marks)
    if not isinstance(marks, dict):
        return
    positions = cast('dict[str, object]', marks).get('positions')
    if isinstance(positions, dict):
        for position in cast('dict[str, object]', positions).values():
            validate_temporal_text(position)


def encode_viewer_record(author: str, post_id: str, marks: PostMarks) -> bytes:
    """Encode one post's marks as UTF-8 JSON without changing the input."""
    try:
        document = _ViewerDocument(
            schema_version=VIEWER_SCHEMA_VERSION,
            author=author,
            post_id=post_id,
            marks=marks,
        )
        return (document.model_dump_json(indent=2) + '\n').encode('utf-8')
    except ValidationError as error:
        raise InvalidViewerRecordError(_validation_message(error)) from None
    except (ValueError, TypeError, AttributeError) as error:
        message = 'Invalid viewer record: values cannot be encoded'
        raise InvalidViewerRecordError(message) from error


def decode_viewer_record(data: bytes, *, author: str, post_id: str) -> PostMarks:
    """Decode an independent marks snapshot and check its full post identity."""
    raw = _read_document(data)
    try:
        _validate_temporal_text(raw)
        document = _ViewerDocument.model_validate_json(data)
    except ValidationError as error:
        raise InvalidViewerRecordError(_validation_message(error)) from None
    except ValueError as error:
        message = f'Invalid viewer record: {error}'
        raise InvalidViewerRecordError(message) from error
    if document.author != author or document.post_id != post_id:
        message = 'Viewer record belongs to another post'
        raise InvalidViewerRecordError(message)
    return document.marks
