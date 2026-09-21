"""A video that is gone for good must not look like a network hiccup.

yt-dlp is faked at the module seam; the errors it raises are the real
yt-dlp types, built the way yt-dlp builds them (the original exception
travels in exc_info).
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

import pytest
from yt_dlp.networking.common import Response
from yt_dlp.networking.exceptions import HTTPError, TransportError
from yt_dlp.utils import DownloadError, ExtractorError, UnsupportedError

from boosty_downloader.infrastructure.external_videos_downloader import (
    external_videos_downloader as module,
)
from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
    ExtVideoDownloadError,
    ExtVideoError,
    ExtVideoInfoError,
    ExtVideoUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

URL = 'https://www.youtube.com/watch?v=gone'


def _download_error(original: BaseException) -> DownloadError:
    """Wrap an exception the way yt-dlp does: the original travels in exc_info."""
    exc_info = (type(original), original, original.__traceback__)
    return DownloadError(f'ERROR: {original}', exc_info)


def _http_error(status: int, reason: str) -> HTTPError:
    response = Response(
        fp=io.BytesIO(b''), url=URL, headers={}, status=status, reason=reason
    )
    return HTTPError(response)


def _fake_yt_dlp(
    monkeypatch: pytest.MonkeyPatch,
    *,
    probe_error: DownloadError | None = None,
    download_error: DownloadError | None = None,
) -> None:
    """yt-dlp that answers the probe and the download as scripted."""

    class _FakeYoutubeDL:
        def __init__(self, params: Any = None) -> None:  # noqa: ANN401 - yt-dlp's own signature
            del params

        # typing.Self needs py3.11+, the package supports 3.10.
        def __enter__(self) -> _FakeYoutubeDL:  # noqa: PYI034
            return self

        def __exit__(self, *args: object) -> bool:
            del args
            return False

        def extract_info(self, url: str, download: bool = True) -> dict[str, Any]:  # noqa: FBT001, FBT002 - yt-dlp's own signature
            del url, download
            if probe_error is not None:
                raise probe_error
            return {'title': 'clip', 'ext': 'mp4'}

        def download(self, urls: Iterable[str]) -> int:
            del urls
            if download_error is not None:
                raise download_error
            return 0

    monkeypatch.setattr(module, 'YoutubeDL', _FakeYoutubeDL)


GONE = [
    pytest.param(
        ExtractorError('This video is unavailable', expected=True),
        'This video is unavailable',
        id='deleted-or-private',
    ),
    pytest.param(
        UnsupportedError('https://example.com/page'),
        'Unsupported URL: https://example.com/page',
        id='unsupported-url',
    ),
    pytest.param(
        _http_error(404, 'Not Found'), 'HTTP Error 404: Not Found', id='page-404'
    ),
]

TRANSIENT = [
    pytest.param(
        ExtractorError('Unable to download webpage', expected=False),
        id='extractor-bug',
    ),
    pytest.param(TransportError('nodename nor servname provided'), id='network-down'),
    pytest.param(_http_error(503, 'Service Unavailable'), id='server-error'),
]


@pytest.mark.parametrize(('original', 'reason'), GONE)
def test_a_gone_video_is_reported_with_the_site_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    original: BaseException,
    reason: str,
) -> None:
    """Five attempts on a deleted video were the whole of issue #76."""
    _fake_yt_dlp(monkeypatch, probe_error=_download_error(original))

    with pytest.raises(ExtVideoUnavailableError) as info:
        ExternalVideosDownloader().download_video(URL, tmp_path)

    assert info.value.reason == reason
    assert info.value.video_url == URL


@pytest.mark.parametrize('original', TRANSIENT)
def test_a_passing_failure_stays_retryable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, original: BaseException
) -> None:
    _fake_yt_dlp(monkeypatch, probe_error=_download_error(original))

    with pytest.raises(ExtVideoInfoError):
        ExternalVideosDownloader().download_video(URL, tmp_path)


@pytest.mark.parametrize(
    ('original', 'expected'),
    [
        pytest.param(
            ExtractorError('Requested format is not available', expected=True),
            ExtVideoUnavailableError,
            id='gone-while-downloading',
        ),
        pytest.param(
            TransportError('connection reset'),
            ExtVideoDownloadError,
            id='network-while-downloading',
        ),
    ],
)
def test_the_download_phase_tells_the_two_apart_as_well(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    original: BaseException,
    expected: type[ExtVideoError],
) -> None:
    _fake_yt_dlp(monkeypatch, download_error=_download_error(original))

    with pytest.raises(expected):
        ExternalVideosDownloader().download_video(URL, tmp_path)
