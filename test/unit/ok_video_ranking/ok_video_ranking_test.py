from boosty_downloader.application.ok_video_ranking import (
    BoostyOkVideoType,
    BoostyOkVideoUrl,
    RankingDict,
    get_best_video,
    get_quality_ranking,
)
from boosty_downloader.infrastructure.boosty_api.models.unknown_value import (
    BoostyUnknownValue,
)


def test_ranking_dict_basic_operations():
    ranking = RankingDict[str]()
    ranking['a'] = 10
    ranking['b'] = 20
    ranking['c'] = 15

    assert ranking['a'] == 10
    assert ranking['b'] == 20
    assert ranking['c'] == 15

    assert ranking.pop_max() == ('b', 20)
    assert ranking.pop_max() == ('c', 15)
    assert ranking.pop_max() == ('a', 10)
    assert ranking.pop_max() is None


def test_ranking_dict_delete():
    ranking = RankingDict[str]()
    ranking['x'] = 5
    ranking['y'] = 10

    del ranking['x']
    assert 'x' not in ranking.data
    assert ranking.pop_max() == ('y', 10)
    assert ranking.pop_max() is None


def test_get_quality_ranking():
    ranking = get_quality_ranking()
    assert ranking[BoostyOkVideoType.ultra_hd] == 17
    assert ranking[BoostyOkVideoType.lowest] == 10
    assert ranking.pop_max() == (BoostyOkVideoType.ultra_hd, 17)
    assert ranking.pop_max() == (BoostyOkVideoType.quad_hd, 16)
    assert ranking.pop_max() == (BoostyOkVideoType.full_hd, 15)


def test_get_best_video():
    video_urls = [
        BoostyOkVideoUrl(type=BoostyOkVideoType.low, url='low.mp4'),
        BoostyOkVideoUrl(type=BoostyOkVideoType.medium, url='medium.mp4'),
        BoostyOkVideoUrl(type=BoostyOkVideoType.full_hd, url='full_hd.mp4'),
    ]

    best_video_info = get_best_video(video_urls)
    best_video = best_video_info[0] if best_video_info else None
    assert best_video is not None
    assert best_video.type == BoostyOkVideoType.medium  # Default preference
    assert best_video.url == 'medium.mp4'


def test_get_best_video_with_preference():
    video_urls = [
        BoostyOkVideoUrl(type=BoostyOkVideoType.low, url='low.mp4'),
        BoostyOkVideoUrl(type=BoostyOkVideoType.full_hd, url='full_hd.mp4'),
    ]

    best_video_info = get_best_video(
        video_urls, preferred_quality=BoostyOkVideoType.full_hd
    )

    best_video = best_video_info[0] if best_video_info else None

    assert best_video is not None
    assert best_video.type == BoostyOkVideoType.full_hd
    assert best_video.url == 'full_hd.mp4'


def test_get_best_video_no_available():
    video_urls = [
        BoostyOkVideoUrl(type=BoostyOkVideoType.low, url=''),  # No valid URL
        BoostyOkVideoUrl(type=BoostyOkVideoType.medium, url=''),
    ]

    best_video = get_best_video(video_urls)
    assert best_video is None


def test_get_best_video_empty_list():
    best_video = get_best_video([])
    assert best_video is None


def test_ranking_dict_with_duplicate_entries():
    ranking = RankingDict[str]()
    ranking['a'] = 10
    ranking['b'] = 20
    ranking['a'] = 30  # Overwriting "a" with a higher value

    assert ranking.pop_max() == ('a', 30)
    assert ranking.pop_max() == ('b', 20)
    assert ranking.pop_max() is None


def test_known_quality_beats_unknown_type():
    video_urls = [
        BoostyOkVideoUrl(
            url='https://vd.example/unknown',
            type=BoostyUnknownValue(raw='imaginary_dash'),
        ),
        BoostyOkVideoUrl(
            url='https://vd.example/medium', type=BoostyOkVideoType.medium
        ),
    ]

    best_video = get_best_video(video_urls)

    assert best_video is not None
    assert best_video[1] == BoostyOkVideoType.medium


def test_only_unknown_types_gives_none():
    video_urls = [
        BoostyOkVideoUrl(
            url='https://vd.example/unknown',
            type=BoostyUnknownValue(raw='imaginary_dash'),
        ),
    ]

    assert get_best_video(video_urls) is None


def test_stream_manifest_is_never_selected():
    """A manifest url handed to download_file lands on disk as a text file."""
    video_urls = [
        BoostyOkVideoUrl(
            url='https://vd.example/video.m3u8', type=BoostyOkVideoType.hls
        ),
        BoostyOkVideoUrl(url='https://vd.example/mpd', type=BoostyOkVideoType.dash),
    ]

    assert get_best_video(video_urls) is None


def test_progressive_beats_a_stream_regardless_of_rank():
    """The lowest mp4 is a real video; the best manifest is not downloadable."""
    video_urls = [
        BoostyOkVideoUrl(
            url='https://vd.example/video.m3u8', type=BoostyOkVideoType.hls
        ),
        BoostyOkVideoUrl(url='https://vd.example/tiny', type=BoostyOkVideoType.tiny),
    ]

    best_video = get_best_video(video_urls)

    assert best_video is not None
    assert best_video[1] == BoostyOkVideoType.tiny
