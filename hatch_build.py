"""Require built viewer assets in distributable wheels."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Keep editable Python installs independent of the frontend toolchain."""

    def initialize(self, version: str, _build_data: dict[str, object]) -> None:
        if version != 'standard':
            return
        index = Path(self.root) / 'boosty_downloader/viewer/static/app/index.html'
        if not index.is_file():
            message = 'Viewer assets are missing. Run `task ui:build` before building a wheel.'
            raise FileNotFoundError(message)
