"""Storage-neutral validation and independent snapshots of user viewing marks."""

from dataclasses import replace
from typing import Annotated, Final

from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError

from boosty_downloader.domain.library_marks import PostMarks
from boosty_downloader.infrastructure.library._record_validation import (
    optional_utc,
    require_identity,
    require_nonnegative,
)
from boosty_downloader.infrastructure.library.errors import InvalidViewerRecordError

MARKS_VALUE_CONFIG: Final = ConfigDict(
    extra='forbid',
    hide_input_in_errors=True,
    strict=True,
    revalidate_instances='always',
    allow_inf_nan=False,
)


def validate_marks_fields(marks: PostMarks) -> PostMarks:
    """Normalize clocks while preserving every nonblank post-local media identity."""
    for media_id, position in marks.positions.items():
        require_identity(media_id, 'media_id')
        require_nonnegative(seconds=position.seconds)
    return replace(
        marks,
        seen_at=optional_utc(marks.seen_at, 'seen_at'),
        positions={
            media_id: replace(
                position, finished_at=optional_utc(position.finished_at, 'finished_at')
            )
            for media_id, position in marks.positions.items()
        },
    )


def marks_validation_message(error: ValidationError) -> str:
    """Describe invalid fields without exposing private media identities or values."""
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


class _MarksValue(BaseModel):
    model_config = MARKS_VALUE_CONFIG
    marks: Annotated[PostMarks, AfterValidator(validate_marks_fields)]


def validate_marks_snapshot(marks: PostMarks) -> PostMarks:
    """Return strictly validated marks with independent nested playback positions."""
    try:
        return _MarksValue(marks=marks).marks
    except ValidationError as error:
        raise InvalidViewerRecordError(marks_validation_message(error)) from None
