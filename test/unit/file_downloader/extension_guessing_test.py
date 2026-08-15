"""Regression tests for #75: the extension policy follows the name's origin.

Names from the author (files, audio) already carry their extension and are
never touched. Names built by the app (videos, images) have no extension by
construction - the content type appends one, and "type unknown" appends
nothing, so ".bin" files are never born.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from boosty_downloader.src.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.src.domain.post import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkFile,
    PostDataChunkImage,
)
from boosty_downloader.src.infrastructure.file_downloader import _extension_to_append

if TYPE_CHECKING:
    import pytest

    from boosty_downloader.src.application.di.download_context import DownloadContext
    from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO


def test_type_unknown_never_produces_an_extension() -> None:
    """'application/octet-stream' means "bytes" - .bin must not be born from it."""
    assert _extension_to_append('application/octet-stream') is None
    assert _extension_to_append(None) is None


def test_informative_content_type_gives_the_extension() -> None:
    assert _extension_to_append('video/mp4') == '.mp4'
    assert _extension_to_append('image/png') == '.png'


def _use_case_with_captured_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[DownloadSinglePostUseCase, dict[str, bool]]:
    captured: dict[str, bool] = {}

    async def fake_download(
        self: DownloadSinglePostUseCase,
        **kwargs: object,
    ) -> Path:
        del self
        captured[str(kwargs['filename'])] = bool(kwargs.get('guess_extension', True))
        return Path(str(kwargs['filename']))

    monkeypatch.setattr(
        DownloadSinglePostUseCase, '_download_with_progress', fake_download
    )
    use_case = DownloadSinglePostUseCase(
        destination=Path('unused'),
        post_dto=cast('PostDTO', None),
        download_context=cast('DownloadContext', None),
    )
    return use_case, captured


async def test_author_names_are_never_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The #75 regression: flipping files back to guessing revives .bin."""
    use_case, captured = _use_case_with_captured_flags(monkeypatch)

    await use_case.download_files(PostDataChunkFile(url='u', filename='any.appimage'))
    await use_case.download_audio(PostDataChunkAudio(url='u', title='song.mp3'))

    assert captured == {'any.appimage': False, 'song.mp3': False}


async def test_app_built_names_ask_for_an_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Videos and images have no extension by construction - the content type adds one."""
    use_case, captured = _use_case_with_captured_flags(monkeypatch)

    await use_case.download_boosty_video(
        PostDataChunkBoostyVideo(
            id='a2dd6942', title='Update v1.2', url='u', quality='medium'
        )
    )
    await use_case.download_image(PostDataChunkImage(url='https://cdn/image/40f9e868'))

    assert len(captured) == 2
    assert all(captured.values()), f'both must ask for an extension: {captured}'
