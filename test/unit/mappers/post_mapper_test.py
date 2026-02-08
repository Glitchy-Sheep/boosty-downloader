from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from boosty_downloader.src.application.filtering import DownloadContentTypeFilter
from boosty_downloader.src.application.mappers.post_mapper import (
    PostMappingResult,
    map_post_dto_to_domain,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO

if TYPE_CHECKING:
    from boosty_downloader.src.infrastructure.boosty_api.models.post.base_post_data import (
        BasePostData,
    )
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_audio import (
    BoostyPostDataAudioDTO,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
    BoostyOkVideoUrl,
    BoostyPostDataOkVideoDTO,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_text import (
    BoostyPostDataTextDTO,
)


def _make_post_dto(data: list[BasePostData]) -> PostDTO:
    return PostDTO(
        id='test-uuid-1234',
        title='Test Post',
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        has_access=True,
        signed_query='sig=abc',
        data=data,
    )


def _make_ok_video(
    *, complete: bool, upload_status: str | None = None
) -> BoostyPostDataOkVideoDTO:
    return BoostyPostDataOkVideoDTO(
        type='ok_video',
        title='test video',
        failover_host='https://example.com',
        duration=timedelta(seconds=120),
        upload_status=upload_status,
        complete=complete,
        player_urls=[
            BoostyOkVideoUrl(
                type=BoostyOkVideoType.medium, url='https://example.com/video.mp4'
            ),
        ],
    )


def _make_audio(
    *, complete: bool, upload_status: str | None = None
) -> BoostyPostDataAudioDTO:
    return BoostyPostDataAudioDTO(
        type='audio_file',
        id='audio-1',
        url='https://example.com/audio.mp3',
        title='test audio',
        size=1024,
        complete=complete,
        time_code=0,
        show_views_counter=False,
        upload_status=upload_status,
        views_counter=0,
    )


def test_complete_ok_video_is_mapped():
    post_dto = _make_post_dto([_make_ok_video(complete=True, upload_status='ok')])
    result = map_post_dto_to_domain(
        post_dto, preferred_video_quality=BoostyOkVideoType.medium
    )

    assert isinstance(result, PostMappingResult)
    assert len(result.post.post_data_chunks) == 1
    assert not result.incomplete_content_types


def test_incomplete_ok_video_is_skipped():
    post_dto = _make_post_dto([_make_ok_video(complete=False)])
    result = map_post_dto_to_domain(
        post_dto, preferred_video_quality=BoostyOkVideoType.medium
    )

    assert len(result.post.post_data_chunks) == 0
    assert DownloadContentTypeFilter.boosty_videos in result.incomplete_content_types


def test_incomplete_ok_video_with_null_upload_status():
    post_dto = _make_post_dto([_make_ok_video(complete=False, upload_status=None)])
    result = map_post_dto_to_domain(
        post_dto, preferred_video_quality=BoostyOkVideoType.medium
    )

    assert len(result.post.post_data_chunks) == 0
    assert DownloadContentTypeFilter.boosty_videos in result.incomplete_content_types


def test_complete_audio_is_mapped():
    post_dto = _make_post_dto([_make_audio(complete=True)])
    result = map_post_dto_to_domain(
        post_dto, preferred_video_quality=BoostyOkVideoType.medium
    )

    assert len(result.post.post_data_chunks) == 1
    assert not result.incomplete_content_types


def test_incomplete_audio_is_skipped():
    post_dto = _make_post_dto([_make_audio(complete=False)])
    result = map_post_dto_to_domain(
        post_dto, preferred_video_quality=BoostyOkVideoType.medium
    )

    assert len(result.post.post_data_chunks) == 0
    assert DownloadContentTypeFilter.audio in result.incomplete_content_types


def test_mixed_post_with_incomplete_video_and_complete_text():
    text_chunk = BoostyPostDataTextDTO(
        type='text',
        content='Hello world',
        modificator='',
    )
    post_dto = _make_post_dto(
        [
            text_chunk,
            _make_ok_video(complete=False),
            _make_audio(complete=True),
        ]
    )
    result = map_post_dto_to_domain(
        post_dto, preferred_video_quality=BoostyOkVideoType.medium
    )

    # Text and audio should be mapped, incomplete video skipped
    assert len(result.post.post_data_chunks) == 2
    assert DownloadContentTypeFilter.boosty_videos in result.incomplete_content_types
    assert DownloadContentTypeFilter.audio not in result.incomplete_content_types
