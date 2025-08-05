"""Defines panels for grouping arguments in the CLI help interface."""

from enum import Enum


class HelpPanels(str, Enum):
    """Panels for groupping arguments in the CLI help."""

    actions = 'Actions'
    filtering = 'Filtering'
    network = 'Network'
