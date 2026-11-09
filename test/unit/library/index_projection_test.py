"""Index projections retain canonical content, media history and viewer choices."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from boosty_downloader.domain.library import LibraryPost, PostAccess, PostOverview
from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    LineBreak,
    ListBlock,
    ListItem,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    ParagraphBreak,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.library.index_projection import (
    fold_search_text,
    project_author,
    project_post,
)
from boosty_downloader.infrastructure.library.index_sources import (
    AuthorSource,
    PostSource,
    SourceFingerprint,
)

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
POST_ID = '00000000-0000-4000-8000-000000000001'
FOLDER = 'teacher/2026-11-09_Lesson_00000000'
VIDEO_ID = 'boosty_video:lesson'
IMAGE_ID = 'image:diagram'


def _text(value: str) -> TextBlock:
    return TextBlock([PostDataChunkText.TextFragment(value)])


@pytest.fixture
def saved_post() -> StoredPost:
    return StoredPost(
        post=PostMetadata(
            id=POST_ID,
            author='teacher',
            url=f'https://boosty.to/teacher/posts/{POST_ID}',
            title='Урок о ёлках',
            created_at=NOW,
            updated_at=NOW,
            tags=['lesson'],
            content_counters={'video': 1},
        ),
        sync=PostSync(NOW, NOW),
        blocks=[_text('Сохранённый урок'), MediaBlock(VIDEO_ID)],
        media={
            VIDEO_ID: MediaEntry(
                kind=MediaKind.boosty_video,
                status=MediaStatus.downloaded,
                added_at=NOW,
                position=0,
                path='lesson.mp4',
                size=500,
                preview_path='lesson.jpg',
            ),
        },
    )


def _source(record: StoredPost, marks: PostMarks | None = None) -> PostSource:
    return PostSource(
        LibraryPost(PostOverview(record.post, PostAccess.open), record, FOLDER),
        marks=marks if marks is not None else PostMarks(),
        record_fingerprint=SourceFingerprint(10, 200),
        marks_fingerprint=SourceFingerprint(20, 100),
        cover_path=f'{FOLDER}/lesson.jpg',
    )


def test_body_order_deduplicates_before_inventory_and_removed_order(
    saved_post: StoredPost,
) -> None:
    video = saved_post.media[VIDEO_ID]
    saved_post.media = {
        'file:removed-last': replace(
            video, kind=MediaKind.file, position=30, removed_at=NOW
        ),
        'file:extra-last': replace(video, kind=MediaKind.file, position=20),
        VIDEO_ID: replace(video, position=10),
        'file:removed-first': replace(
            video, kind=MediaKind.file, position=0, removed_at=NOW
        ),
        'file:extra-first': replace(video, kind=MediaKind.file, position=5),
        IMAGE_ID: replace(video, kind=MediaKind.image, position=15),
    }
    saved_post.blocks = [
        MediaBlock(IMAGE_ID),
        MediaBlock(VIDEO_ID),
        MediaBlock(IMAGE_ID),
    ]

    projected = project_post(_source(saved_post))

    assert [item.media_id for item in projected.media] == [
        IMAGE_ID,
        VIDEO_ID,
        'file:extra-first',
        'file:extra-last',
        'file:removed-first',
        'file:removed-last',
    ]
    assert [item.position for item in projected.media] == list(range(6))


def test_removed_downloaded_files_remain_without_inflating_current_counts(
    saved_post: StoredPost,
) -> None:
    video = saved_post.media[VIDEO_ID]
    saved_post.media.update(
        {
            'boosty_video:pending': replace(
                video, status=MediaStatus.pending, position=1
            ),
            'boosty_video:removed': replace(video, removed_at=NOW, position=2),
        }
    )

    projected = project_post(_source(saved_post))

    assert projected.current_counts[MediaKind.boosty_video] == 2
    assert projected.downloaded_counts[MediaKind.boosty_video] == 1
    assert sum(projected.current_counts.values()) == 2
    assert sum(projected.downloaded_counts.values()) == 1
    removed = projected.media[-1].entry
    assert removed.status is MediaStatus.downloaded
    assert removed.size == 500
    assert removed.path == 'lesson.mp4'


def test_piece_date_includes_downloaded_history_but_not_unsaved_removals(
    saved_post: StoredPost,
) -> None:
    video = saved_post.media[VIDEO_ID]
    retained_date = NOW + timedelta(days=1)
    later_date = NOW + timedelta(days=2)
    saved_post.media.update(
        {
            'boosty_video:retained': replace(
                video, added_at=retained_date, removed_at=later_date, position=1
            ),
            'boosty_video:pending': replace(
                video,
                added_at=later_date,
                removed_at=later_date,
                status=MediaStatus.pending,
                position=2,
            ),
            'boosty_video:deleted': replace(
                video,
                added_at=later_date,
                removed_at=later_date,
                status=MediaStatus.deleted,
                position=3,
            ),
        }
    )

    assert project_post(_source(saved_post)).pieces_added_at == retained_date

    saved_post.media['boosty_video:current'] = replace(
        video, added_at=later_date, status=MediaStatus.pending, position=4
    )
    assert project_post(_source(saved_post)).pieces_added_at == later_date


def test_only_unsaved_removed_pieces_have_no_piece_date(saved_post: StoredPost) -> None:
    saved_post.blocks = []
    saved_post.media[VIDEO_ID].status = MediaStatus.deleted
    saved_post.media[VIDEO_ID].removed_at = NOW

    assert project_post(_source(saved_post)).pieces_added_at is None


def test_access_overlay_keeps_saved_body_media_marks_and_source_versions(
    saved_post: StoredPost,
) -> None:
    current_metadata = replace(
        saved_post.post, title='Новый платный урок', tags=['updated'], tier='Supporter'
    )
    marks = PostMarks(
        seen_at=NOW, favorite=True, positions={VIDEO_ID: PlaybackPosition(45.5, NOW)}
    )
    source = replace(
        _source(saved_post, marks),
        post=LibraryPost(
            PostOverview(current_metadata, PostAccess.locked),
            saved_post,
            FOLDER,
            '.boosty/teasers/lesson.jpg',
        ),
    )

    projected = project_post(source)

    assert projected.metadata == current_metadata
    assert projected.access is PostAccess.locked
    assert projected.origin == 'api'
    assert projected.text == 'Сохранённый урок'
    assert projected.media[0].entry == saved_post.media[VIDEO_ID]
    assert projected.media[0].playback == PlaybackPosition(45.5, NOW)
    assert projected.marks == marks
    assert projected.folder == FOLDER
    assert projected.teaser_path == '.boosty/teasers/lesson.jpg'
    assert projected.record_fingerprint == source.record_fingerprint
    assert projected.marks_fingerprint == source.marks_fingerprint
    assert projected.cover_path == source.cover_path


def test_locked_only_remote_counters_do_not_invent_local_media(
    saved_post: StoredPost,
) -> None:
    metadata = replace(saved_post.post, content_counters={'video': 12, 'image': 5})
    source = PostSource(LibraryPost(PostOverview(metadata, PostAccess.locked)))

    projected = project_post(source)

    assert projected.metadata == metadata
    assert projected.origin == 'locked'
    assert projected.access is PostAccess.locked
    assert projected.folder is None
    assert projected.text == projected.excerpt == ''
    assert projected.media == ()
    assert projected.pieces_added_at is None
    assert projected.current_counts == dict.fromkeys(MediaKind, 0)
    assert projected.downloaded_counts == dict.fromkeys(MediaKind, 0)


def test_plain_body_preserves_nested_lists_breaks_and_literal_user_markup(
    saved_post: StoredPost,
) -> None:
    saved_post.blocks = [
        TextBlock(
            [
                PostDataChunkText.TextFragment('<script>literal</script>'),
                LineBreak(),
                PostDataChunkText.TextFragment('second line'),
            ]
        ),
        ParagraphBreak(),
        ListBlock(
            [
                ListItem([_text('parent')], [ListItem([_text('child')])]),
                ListItem([_text('sibling')]),
            ]
        ),
        MediaBlock(VIDEO_ID),
        _text('after video'),
    ]
    saved_post.media[VIDEO_ID].title = 'Generated media label'

    projected = project_post(_source(saved_post))

    assert projected.text == (
        '<script>literal</script>\nsecond line\n\nparent\nchild\nsibling\n\nafter video'
    )
    assert projected.excerpt == (
        '<script>literal</script> second line parent child sibling after video'
    )
    assert 'Generated media label' not in projected.text
    assert 'lesson.mp4' not in projected.text


@pytest.mark.parametrize('control', ['\x00', '\x02', '\x03'])
def test_search_controls_become_spaces_without_merging_words(
    saved_post: StoredPost,
    control: str,
) -> None:
    saved_post.post.title = f'one{control}two{control}three'
    saved_post.blocks = [_text(f'ёлка{control}сосна{control}кедр')]

    projected = project_post(_source(saved_post))

    assert projected.metadata.title == f'one{control}two{control}three'
    assert projected.title == projected.title_folded == 'one two three'
    assert projected.text == 'ёлка сосна кедр'
    assert projected.text_folded == 'елка сосна кедр'


def test_search_folding_preserves_offsets_and_short_i_distinction() -> None:
    original = 'Ёлка ёж йод ЙОД café CAFÉ 👩‍💻'

    folded = fold_search_text(original)

    assert folded == 'Елка еж йод ЙОД café CAFÉ 👩‍💻'
    assert len(folded) == len(original)
    assert folded.index('йод') == original.index('йод')


def test_excerpt_collapses_whitespace_and_limits_preview(
    saved_post: StoredPost,
) -> None:
    saved_post.blocks = [_text('  introduction\n\n' + 'word ' * 100)]

    projected = project_post(_source(saved_post))

    assert len(projected.excerpt) == 240
    assert projected.excerpt.startswith('introduction word word')
    assert '\n' not in projected.excerpt
    assert len(projected.text) > len(projected.excerpt)


def test_thumbnails_use_library_relative_paths_without_checking_disk(
    saved_post: StoredPost,
) -> None:
    saved_post.media[VIDEO_ID].status = MediaStatus.pending
    saved_post.media[IMAGE_ID] = MediaEntry(
        MediaKind.image,
        MediaStatus.downloaded,
        NOW,
        1,
        path='images/diagram.png',
        size=42,
    )
    saved_post.media['image:pending'] = replace(
        saved_post.media[IMAGE_ID], status=MediaStatus.pending, position=2
    )

    projected = project_post(_source(saved_post))
    video, image, pending_image = projected.media

    assert video.thumbnail_path == f'{FOLDER}/lesson.jpg'
    assert video.entry.status is MediaStatus.pending
    assert image.thumbnail_path == f'{FOLDER}/images/diagram.png'
    assert image.entry.path == 'images/diagram.png'
    assert image.entry.size == 42
    assert pending_image.thumbnail_path is None


def test_post_projection_owns_independent_nested_snapshots(
    saved_post: StoredPost,
) -> None:
    marks = PostMarks(
        seen_at=NOW, favorite=True, positions={VIDEO_ID: PlaybackPosition(45.5, NOW)}
    )
    source = _source(saved_post, marks)
    original = deepcopy(source)
    projected = project_post(source)

    projected.metadata.tags.append('changed')
    projected.metadata.content_counters['video'] = 99
    projected.media[0].entry.size = 1
    playback = projected.media[0].playback
    assert playback is not None
    playback.seconds = 0
    projected.marks.positions[VIDEO_ID].seconds = 10
    projected.marks.favorite = False

    assert source == original
    assert projected.marks.positions[VIDEO_ID].seconds != playback.seconds
    assert project_post(source).marks == original.marks


def test_marks_for_absent_media_are_retained(saved_post: StoredPost) -> None:
    marks = PostMarks(positions={'audio:old': PlaybackPosition(100, NOW)})

    projected = project_post(_source(saved_post, marks))

    assert projected.marks.positions == marks.positions
    assert projected.media[0].playback is None


def test_saved_record_requires_a_folder(saved_post: StoredPost) -> None:
    source = PostSource(
        LibraryPost(PostOverview(saved_post.post, PostAccess.open), saved_post)
    )

    with pytest.raises(ValueError, match='library-relative post folder'):
        project_post(source)


def test_author_projection_preserves_metadata_and_fingerprints_independently() -> None:
    info = AuthorInfo('teacher', NOW, title='Lessons', description='Full\n\nbiography')
    source = AuthorSource(
        'teacher',
        info,
        author_fingerprint=SourceFingerprint(10, 100),
        locked_fingerprint=SourceFingerprint(20, 200),
    )

    projected = project_author(source)

    assert projected.info == info
    assert projected.author_fingerprint == source.author_fingerprint
    assert projected.locked_fingerprint == source.locked_fingerprint
    assert projected.info is not None
    projected.info.description = 'changed'
    assert info.description == 'Full\n\nbiography'
    assert project_author(AuthorSource('teacher')).info is None
