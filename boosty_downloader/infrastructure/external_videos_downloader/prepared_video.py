"""Typed prepared metadata and the completed yt-dlp output capture."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.utils import PostProcessingError

YtVideoInfo: TypeAlias = dict[str, Any]
PostProcessorResult: TypeAlias = tuple[list[str], Any]

if TYPE_CHECKING:
    from yt_dlp.YoutubeDL import YoutubeDL


@dataclass(frozen=True, slots=True)
class PreparedExternalVideo:
    """A concrete filename plus metadata kept inside the yt-dlp adapter."""

    url: str
    title: str
    filename: str
    _info: YtVideoInfo = field(repr=False)

    def process(self, downloader: YoutubeDL) -> None:
        """Consume a private metadata copy without extracting the URL again."""
        cast('Any', downloader).process_ie_result(deepcopy(self._info), download=True)


class CaptureFinalFilePP(PostProcessor):
    """Record the actual file after all postprocessing and moves finish."""

    def __init__(self) -> None:
        super().__init__()
        self.path: Path | None = None

    def run(self, information: Any) -> PostProcessorResult:  # noqa: ANN401 - yt-dlp owns the evolving info dictionary
        path = information.get('filepath')
        if self.path is not None or not isinstance(path, str) or not path:
            message = 'Expected one completed external video file'
            raise PostProcessingError(message)
        self.path = Path(path)
        return [], information
