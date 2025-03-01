from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_ok_video import (
    OkVideoType,
    OkVideoUrl,
)
from boosty_downloader.src.download_manager.ok_video_ranking import (
    RankingDict,
    get_best_video,
    get_quality_ranking,
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
    assert ranking[OkVideoType.ultra_hd] == 17
    assert ranking[OkVideoType.lowest] == 10
    assert ranking.pop_max() == (OkVideoType.ultra_hd, 17)
    assert ranking.pop_max() == (OkVideoType.quad_hd, 16)
    assert ranking.pop_max() == (OkVideoType.full_hd, 15)


def test_get_best_video():
    video_urls = [
        OkVideoUrl(type=OkVideoType.low, url='low.mp4'),
        OkVideoUrl(type=OkVideoType.medium, url='medium.mp4'),
        OkVideoUrl(type=OkVideoType.full_hd, url='full_hd.mp4'),
    ]

    best_video = get_best_video(video_urls)
    assert best_video is not None
    assert best_video.type == OkVideoType.medium  # Default preference
    assert best_video.url == 'medium.mp4'


def test_get_best_video_with_preference():
    video_urls = [
        OkVideoUrl(type=OkVideoType.low, url='low.mp4'),
        OkVideoUrl(type=OkVideoType.full_hd, url='full_hd.mp4'),
    ]

    best_video = get_best_video(video_urls, preferred_quality=OkVideoType.full_hd)
    assert best_video is not None
    assert best_video.type == OkVideoType.full_hd
    assert best_video.url == 'full_hd.mp4'


def test_get_best_video_no_available():
    video_urls = [
        OkVideoUrl(type=OkVideoType.low, url=''),  # No valid URL
        OkVideoUrl(type=OkVideoType.medium, url=''),
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
