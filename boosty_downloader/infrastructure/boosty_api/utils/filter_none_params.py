"""Just a little helper to make requests"""

from __future__ import annotations

from typing import Any


def filter_none_params(kwargs: dict[str, Any | None]) -> dict[str, Any]:
    """Remove None values from kwargs"""
    return {k: v for k, v in kwargs.items() if v is not None}
