"""
PyPI update checker

Provides functions and data structures to check for updates of any package on PyPI.
"""

import json
from dataclasses import dataclass
from enum import Enum, auto
from urllib.request import urlopen

from packaging import version


class UpdateCheckStatus(Enum):
    """Represents the status of an update check."""

    NO_UPDATE = auto()
    UPDATE_AVAILABLE = auto()
    CHECK_FAILED = auto()


@dataclass
class UpdateAvailable:
    """Update is available."""

    current_version: str
    latest_version: str


@dataclass
class NoUpdate:
    """No update available."""


@dataclass
class CheckFailed:
    """Update check failed."""


UpdateResult = UpdateAvailable | NoUpdate | CheckFailed


def get_pypi_latest_version(package_name: str) -> str | None:
    """Fetch the latest version string of a package from PyPI."""
    try:
        with urlopen(f'https://pypi.org/pypi/{package_name}/json') as resp:
            data = json.load(resp)
            return data['info']['version']
    except Exception:  # noqa: BLE001 It doesn't matter what exception is raised, we just need to 100% catch it
        return None


def check_for_updates(current_version: str, package_name: str) -> UpdateResult:
    """Check PyPI for a newer version of a package and return update result."""
    latest_str = get_pypi_latest_version(package_name)
    if latest_str is None:
        return CheckFailed()

    try:
        current = version.parse(current_version)
        latest = version.parse(latest_str)
    except version.InvalidVersion:
        return CheckFailed()

    if latest > current:
        return UpdateAvailable(
            current_version=str(current),
            latest_version=str(latest),
        )

    return NoUpdate()
