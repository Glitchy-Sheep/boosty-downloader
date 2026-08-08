"""Wrapper for API values this client doesn't know yet."""

from dataclasses import dataclass
from typing import Annotated

from pydantic import BeforeValidator


@dataclass(frozen=True, slots=True)
class BoostyUnknownValue:
    """
    A value from the Boosty API this client doesn't know yet.

    Keeps the raw word so the run summary can name it and the user
    can report it. Known values live in their enums; this type marks
    everything outside of them.
    """

    raw: str


def _wrap_raw_value(value: object) -> object:
    if isinstance(value, BoostyUnknownValue):
        return value
    return BoostyUnknownValue(raw=str(value))


# Field-annotation form: any non-enum value is wrapped, keeping the raw word.
# Place it LAST in a union (after the enum and None) with
# union_mode='left_to_right', otherwise it swallows known values too.
UnknownValue = Annotated[BoostyUnknownValue, BeforeValidator(_wrap_raw_value)]
