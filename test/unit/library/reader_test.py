"""Indexed library queries preserve canonical identities and user-owned marks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import copytree
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from boosty_downloader.domain.library import LibraryContentKind, PostAccess, PostFilters
from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    LockedPost,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.library import index_sources
from boosty_downloader.infrastructure.library._index_models import IndexMedia, IndexPost
from boosty_downloader.infrastructure.library.errors import (
    InvalidPostRecordError,
    InvalidViewerRecordError,
)
from boosty_downloader.infrastructure.library.index import (
    IndexNotPreparedError,
    LibraryIndex,
)
from boosty_downloader.infrastructure.library.json_store import write_post_record
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=1)
POST_ID = 'abcdefgh-first'
AUDIO_ID = 'audio:lesson'


@dataclass(frozen=True)
class LibraryFixture:
    root: Path
    store: JsonPostStore
    folder: str
    record: StoredPost


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / 'library'
    initialize_library(path)
    return path


@pytest.fixture
def library(root: Path) -> LibraryFixture:
    store = JsonPostStore(root)
    record = _record(POST_ID, title='Всё о шейдерах')
    record.post.tags = ['second', 'first', 'second']
    record.post.content_counters = {'audio': 1}
    record.post.published_at = NOW
    record.post.tier = 'Supporter'
    record.post.tier_price_rub = 150.5
    record.post.post_price_rub = 75.0
    record.post.likes = 12
    record.post.comments = 3
    _add_media(record, MediaKind.audio, AUDIO_ID)
    folder = _save(store, record)
    store.save_author(AuthorInfo('writer', NOW, title='Lessons', remote_post_count=15))
    return LibraryFixture(root, store, folder, record)


@pytest.fixture
def reader(library: LibraryFixture) -> JsonLibraryReader:
    result = JsonLibraryReader(library.root)
    result.prepare()
    return result


def _record(
    post_id: str, *, title: str = 'Lesson', author: str = 'writer'
) -> StoredPost:
    return StoredPost(
        PostMetadata(
            post_id,
            author,
            f'https://boosty.to/{author}/posts/{post_id}',
            title,
            NOW,
            NOW,
        ),
        PostSync(NOW, NOW),
        [TextBlock([PostDataChunkText.TextFragment('Searchable body')])],
    )


def _save(store: JsonPostStore, record: StoredPost) -> str:
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    return folder


def _add_media(record: StoredPost, kind: MediaKind, media_id: str) -> None:
    record.media[media_id] = MediaEntry(
        kind, MediaStatus.pending, NOW, len(record.media)
    )
    record.blocks.append(MediaBlock(media_id))


def _ids(reader: JsonLibraryReader, filters: PostFilters | None = None) -> list[str]:
    return [
        item.post.id for item in reader.list_posts('writer', filters or PostFilters())
    ]


def test_constructor_creates_nothing(tmp_path: Path) -> None:
    root = tmp_path / 'absent'
    JsonLibraryReader(root, index_path=tmp_path / 'cache' / 'index.db')
    assert not root.exists()
    assert not (tmp_path / 'cache').exists()


def test_prepare_reads_external_changes_explicitly(
    library: LibraryFixture, reader: JsonLibraryReader
) -> None:
    library.record.post.title = 'Changed title'
    library.store.save_post(library.folder, library.record)
    assert reader.list_posts('writer', PostFilters())[0].post.title == 'Всё о шейдерах'
    reader.prepare()
    assert reader.list_posts('writer', PostFilters())[0].post.title == 'Changed title'


def test_authors_include_metadata_post_only_and_locked_only(root: Path) -> None:
    store = JsonPostStore(root)
    store.save_author(AuthorInfo('metadata', NOW, title='Metadata only'))
    _save(store, _record(POST_ID, author='saved'))
    locked = _record(POST_ID, author='locked')
    store.save_locked_post(LockedPost(locked.post, NOW))
    reader = JsonLibraryReader(root)
    reader.prepare()
    authors = reader.authors()
    assert [item.author for item in authors] == ['locked', 'metadata', 'saved']
    assert authors[0].info is None
    assert authors[1].info == AuthorInfo('metadata', NOW, title='Metadata only')
    assert authors[2].info is None
    assert reader.list_posts('missing', PostFilters()) == []


def test_lists_read_no_canonical_json(
    reader: JsonLibraryReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = Path.read_bytes

    def guarded_read(path: Path) -> bytes:
        assert path.name not in {
            'author.json',
            'locked.json',
            'post.json',
            'viewer.json',
        }
        return original(path)

    monkeypatch.setattr(Path, 'read_bytes', guarded_read)
    source_read = Mock(
        side_effect=AssertionError('Canonical JSON read during index query')
    )
    monkeypatch.setattr(index_sources, '_read_source', source_read)
    assert reader.authors()[0].author == 'writer'
    assert _ids(reader, PostFilters(text='шейд', tag='second')) == [POST_ID]
    source_read.assert_not_called()


def test_list_snapshots_preserve_metadata_and_nested_independence(
    library: LibraryFixture, reader: JsonLibraryReader
) -> None:
    first = reader.list_posts('writer', PostFilters())[0]
    second = reader.list_posts('writer', PostFilters())[0]
    assert first.post == second.post == library.record.post
    assert first.post.tags == ['second', 'first', 'second']
    first.post.tags.clear()
    first.post.content_counters['audio'] = 99
    assert second.post == library.record.post
    assert reader.list_posts('writer', PostFilters())[0].post == library.record.post
    author = reader.authors()[0]
    assert author.info is not None
    author.info.title = 'Mutated'
    assert reader.authors()[0].info == library.store.load_author('writer')


def test_default_order_uses_creation_time_then_full_id(root: Path) -> None:
    store = JsonPostStore(root)
    for post_id in ['abcdefgh-a', 'abcdefgh-z', 'ijklmnop-new']:
        record = _record(post_id)
        if post_id == 'ijklmnop-new':
            record.post.created_at = LATER
            record.post.updated_at = LATER
        _save(store, record)
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert _ids(reader) == ['ijklmnop-new', 'abcdefgh-z', 'abcdefgh-a']


@pytest.mark.parametrize(
    ('media_kind', 'filter_kind'),
    [
        (MediaKind.boosty_video, LibraryContentKind.video),
        (MediaKind.external_video, LibraryContentKind.video),
        (MediaKind.image, LibraryContentKind.image),
        (MediaKind.file, LibraryContentKind.file),
        (MediaKind.audio, LibraryContentKind.audio),
    ],
)
def test_kind_uses_current_saved_media(
    root: Path, media_kind: MediaKind, filter_kind: LibraryContentKind
) -> None:
    store = JsonPostStore(root)
    record = _record(POST_ID)
    _add_media(record, media_kind, f'{media_kind.value}:one')
    _save(store, record)
    removed = _record('ijklmnop-removed')
    removed.media[f'{media_kind.value}:removed'] = MediaEntry(
        media_kind, MediaStatus.pending, NOW, 0, removed_at=LATER
    )
    removed.post.content_counters = {media_kind.value: 10}
    _save(store, removed)
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert _ids(reader, PostFilters(kind=filter_kind)) == [POST_ID]


@pytest.mark.parametrize(
    ('counter', 'kind'),
    [
        ('ok_video', LibraryContentKind.video),
        ('video', LibraryContentKind.video),
        ('image', LibraryContentKind.image),
        ('file', LibraryContentKind.file),
        ('audio', LibraryContentKind.audio),
    ],
)
def test_locked_only_kind_uses_remote_counters(
    root: Path, counter: str, kind: LibraryContentKind
) -> None:
    store = JsonPostStore(root)
    record = _record(POST_ID)
    record.post.content_counters = {counter: 1}
    store.save_locked_post(LockedPost(record.post, NOW))
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert _ids(reader, PostFilters(kind=kind)) == [POST_ID]
    assert _ids(reader, PostFilters(kind=kind, unseen_only=True)) == []


def test_retained_locked_body_uses_saved_kind_counts(
    library: LibraryFixture, reader: JsonLibraryReader
) -> None:
    locked = replace(library.record.post, content_counters={'video': 20})
    library.store.save_locked_post(LockedPost(locked, LATER))
    reader.prepare()
    assert _ids(reader, PostFilters(kind=LibraryContentKind.video)) == []
    assert _ids(reader, PostFilters(kind=LibraryContentKind.audio)) == [POST_ID]


def test_filters_combine_and_tags_match_exactly(reader: JsonLibraryReader) -> None:
    filters = PostFilters(
        text='все шейд', kind=LibraryContentKind.audio, tag='second', unseen_only=True
    )
    assert _ids(reader, filters) == [POST_ID]
    assert _ids(reader, replace(filters, tag='Second')) == []
    assert _ids(reader, replace(filters, tag='sec')) == []
    assert _ids(reader, replace(filters, kind=LibraryContentKind.video)) == []
    reader.save_marks('writer', POST_ID, PostMarks(seen_at=NOW))
    assert _ids(reader, filters) == []


@pytest.mark.parametrize(
    'query', ['всё ШЕЙД', 'все шейд', '"всё" шейд*', '...!?*"', '___']
)
def test_search_folds_cyrillic_and_treats_punctuation_as_separators(
    reader: JsonLibraryReader, query: str
) -> None:
    assert _ids(reader, PostFilters(text=query)) == [POST_ID]


@pytest.mark.parametrize(
    'query', ['alpha OR beta', '"alpha" AND beta*', 'alpha NOT beta']
)
def test_search_operators_are_literal_words(root: Path, query: str) -> None:
    store = JsonPostStore(root)
    _save(store, _record(POST_ID, title='alpha AND OR NOT beta'))
    _save(store, _record('ijklmnop-other', title='alpha beta'))
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert _ids(reader, PostFilters(text=query)) == [POST_ID]


def test_search_requires_all_words_and_keeps_cyrillic_short_i(root: Path) -> None:
    store = JsonPostStore(root)
    _save(store, _record(POST_ID, title='Мой урок'))
    _save(store, _record('ijklmnop-other', title='Мои уроки'))
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert _ids(reader, PostFilters(text='мой урок')) == [POST_ID]
    assert _ids(reader, PostFilters(text='мой missing')) == []
    assert _ids(reader, PostFilters(text='search body')) == ['ijklmnop-other', POST_ID]


def test_unseen_tracks_new_media_but_not_text_updates(
    library: LibraryFixture, reader: JsonLibraryReader
) -> None:
    reader.save_marks('writer', POST_ID, PostMarks(seen_at=NOW))
    library.record.post.title = 'Edited text'
    library.record.post.updated_at = LATER
    library.store.save_post(library.folder, library.record)
    reader.prepare()
    assert _ids(reader, PostFilters(unseen_only=True)) == []
    _add_media(library.record, MediaKind.file, 'file:new')
    library.record.media['file:new'].added_at = LATER
    library.store.save_post(library.folder, library.record)
    reader.prepare()
    assert _ids(reader, PostFilters(unseen_only=True)) == [POST_ID]


def test_detail_keeps_locked_overview_separate_from_saved_body(
    library: LibraryFixture, reader: JsonLibraryReader
) -> None:
    locked = LockedPost(
        replace(library.record.post, title='Locked title'), LATER, 'teasers/one.jpg'
    )
    library.store.save_locked_post(locked)
    reader.prepare()
    detail = reader.post('writer', POST_ID)
    assert detail is not None
    assert detail.overview.access is PostAccess.locked
    assert detail.overview.post == locked.post
    assert detail.record == library.record
    assert detail.folder == library.folder
    assert detail.teaser_path == locked.teaser_path
    detail.overview.post.tags.clear()
    assert detail.record is not None
    assert detail.record.post.tags == library.record.post.tags
    assert reader.post('writer', 'missing') is None
    assert reader.post('missing', POST_ID) is None


def test_detail_rejects_replaced_full_identity(
    library: LibraryFixture, reader: JsonLibraryReader
) -> None:
    replacement = replace(
        library.record, post=replace(library.record.post, id='abcdefgh-replaced')
    )
    write_post_record(library.root / library.folder, replacement)
    with pytest.raises(InvalidPostRecordError):
        reader.post('writer', POST_ID)


@pytest.mark.parametrize('is_locked', [False, True])
def test_vanished_record_returns_no_body(
    library: LibraryFixture, reader: JsonLibraryReader, *, is_locked: bool
) -> None:
    if is_locked:
        library.store.save_locked_post(LockedPost(library.record.post, LATER))
        reader.prepare()
    (library.root / library.folder / 'post.json').unlink()
    detail = reader.post('writer', POST_ID)
    if is_locked:
        assert detail is not None
        assert detail.overview.access is PostAccess.locked
        assert detail.record is None
        assert detail.folder is None
    else:
        assert detail is None


def test_marks_are_fresh_independent_snapshots(
    library: LibraryFixture, reader: JsonLibraryReader
) -> None:
    marks = PostMarks(
        seen_at=NOW, favorite=True, positions={AUDIO_ID: PlaybackPosition(12.5, LATER)}
    )
    JsonPostMarks(library.root).save_marks('writer', POST_ID, marks)
    first = reader.get_marks('writer', POST_ID)
    assert first == marks
    assert first is not None
    first.positions[AUDIO_ID].seconds = 99
    assert reader.get_marks('writer', POST_ID) == marks
    assert reader.get_marks('writer', 'missing') is None


def test_saving_marks_refreshes_index_without_touching_post(
    library: LibraryFixture, reader: JsonLibraryReader
) -> None:
    path = library.root / library.folder / 'post.json'
    before = path.read_bytes()
    marks = PostMarks(
        seen_at=NOW, favorite=True, positions={AUDIO_ID: PlaybackPosition(12.5, LATER)}
    )
    reader.save_marks('writer', POST_ID, marks)
    assert reader.get_marks('writer', POST_ID) == marks
    assert path.read_bytes() == before
    assert _ids(reader, PostFilters(unseen_only=True)) == []
    with LibraryIndex(library.root).connect() as connection:
        assert connection.scalar(select(IndexPost.favorite)) is True
        assert connection.scalar(select(IndexMedia.playback_position)) == 12.5
        assert connection.scalar(select(IndexMedia.finished_at)) == LATER


def test_marks_remain_durable_when_index_update_fails(
    library: LibraryFixture, reader: JsonLibraryReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = OperationalError('write index', {}, RuntimeError('disk full'))
    monkeypatch.setattr(LibraryIndex, 'upsert_post', Mock(side_effect=failure))
    marks = PostMarks(seen_at=LATER, favorite=True)
    with pytest.raises(OperationalError):
        reader.save_marks('writer', POST_ID, marks)
    assert JsonPostMarks(library.root).get_marks('writer', POST_ID) == marks


def test_invalid_canonical_marks_prevent_index_update(
    library: LibraryFixture, reader: JsonLibraryReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    (library.root / library.folder / 'viewer.json').write_bytes(b'{broken')
    upsert = Mock()
    monkeypatch.setattr(LibraryIndex, 'upsert_post', upsert)
    with pytest.raises(InvalidViewerRecordError):
        reader.save_marks('writer', POST_ID, PostMarks(favorite=True))
    upsert.assert_not_called()


def test_locked_only_marks_cannot_be_saved(root: Path) -> None:
    store = JsonPostStore(root)
    store.save_locked_post(LockedPost(_record(POST_ID).post, NOW))
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert reader.get_marks('writer', POST_ID) == PostMarks()
    with pytest.raises(LookupError):
        reader.save_marks('writer', POST_ID, PostMarks(favorite=True))


def test_text_only_post_is_unseen_until_explicitly_seen(root: Path) -> None:
    store = JsonPostStore(root)
    _save(store, _record(POST_ID))
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert _ids(reader, PostFilters(unseen_only=True)) == [POST_ID]
    reader.save_marks('writer', POST_ID, PostMarks(seen_at=NOW))
    assert _ids(reader, PostFilters(unseen_only=True)) == []


def test_detail_returns_independent_body_and_overview_snapshots(
    library: LibraryFixture, reader: JsonLibraryReader
) -> None:
    first = reader.post('writer', POST_ID)
    second = reader.post('writer', POST_ID)
    assert first is not None
    assert second is not None
    assert first.record is not None
    assert second.record is not None
    first.record.media[AUDIO_ID].title = 'Mutated media'
    first.record.post.tags.clear()
    first.overview.post.content_counters.clear()
    assert second.record == library.record
    assert second.overview.post == library.record.post
    assert reader.post('writer', POST_ID) == second


def test_marks_refresh_uses_current_access_observation(
    library: LibraryFixture, reader: JsonLibraryReader
) -> None:
    locked = LockedPost(replace(library.record.post, title='Fresh locked title'), LATER)
    library.store.save_locked_post(locked)
    reader.save_marks('writer', POST_ID, PostMarks(favorite=True))
    overview = reader.list_posts('writer', PostFilters())[0]
    assert overview.access is PostAccess.locked
    assert overview.post.title == locked.post.title
    assert _ids(reader, PostFilters(unseen_only=True)) == []
    library.store.clear_locked_post('writer', POST_ID)
    reader.save_marks('writer', POST_ID, PostMarks())
    assert reader.list_posts('writer', PostFilters())[0].access is PostAccess.open
    assert _ids(reader, PostFilters(unseen_only=True)) == [POST_ID]


def test_reused_index_rejects_marks_before_changing_canonical_state(
    library: LibraryFixture, tmp_path: Path
) -> None:
    cache = tmp_path / 'cache' / 'index.db'
    reader = JsonLibraryReader(library.root, index_path=cache)
    reader.prepare()
    original = PostMarks(seen_at=NOW)
    reader.save_marks('writer', POST_ID, original)
    copied = tmp_path / 'copied-library'
    copytree(library.root, copied)
    JsonLibraryReader(copied, index_path=cache).prepare()

    with pytest.raises(IndexNotPreparedError):
        reader.save_marks('writer', POST_ID, PostMarks(favorite=True))
    assert JsonPostMarks(library.root).get_marks('writer', POST_ID) == original
    assert JsonPostMarks(copied).get_marks('writer', POST_ID) == original


@pytest.mark.parametrize(
    ('title', 'query'),
    [
        pytest.param('Caféine', 'Caféine', id='composed-exact'),
        pytest.param('Cafe\u0301ine', 'Cafe\u0301ine', id='decomposed-exact'),
        pytest.param('Caféine', 'Cafe\u0301ine', id='composed-title-decomposed-query'),
        pytest.param('Cafe\u0301ine', 'Caféine', id='decomposed-title-composed-query'),
    ],
)
def test_search_matches_latin_combining_accents(
    root: Path, title: str, query: str
) -> None:
    store = JsonPostStore(root)
    _save(store, _record(POST_ID, title=title))
    _save(store, _record('ijklmnop-other', title='Unrelated lesson'))
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert _ids(reader, PostFilters(text=query)) == [POST_ID]


@pytest.mark.parametrize(
    ('title', 'query'),
    [
        pytest.param('Мо\u0301й урок', 'мо\u0301й', id='stress-exact'),
        pytest.param('Мо\u0301й урок', 'мой', id='unstressed-query'),
        pytest.param('Мой урок', 'мо\u0301й', id='stressed-query'),
    ],
)
def test_search_ignores_combining_stress_without_merging_cyrillic_letters(
    root: Path, title: str, query: str
) -> None:
    store = JsonPostStore(root)
    _save(store, _record(POST_ID, title=title))
    _save(store, _record('ijklmnop-other', title='Мои уроки'))
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert _ids(reader, PostFilters(text=query)) == [POST_ID]


@pytest.mark.parametrize(
    ('word', 'query'),
    [
        pytest.param('Caféine', 'Cafe\u0301ine synth', id='latin-exact-and-prefix'),
        pytest.param('Cafe\u0301ine', 'Café synth', id='latin-two-prefixes'),
        pytest.param('Мо\u0301й', 'мо\u0301й synth', id='russian-stress-and-prefix'),
    ],
)
def test_search_combining_accents_preserve_prefix_and_following_word(
    root: Path, word: str, query: str
) -> None:
    store = JsonPostStore(root)
    _save(store, _record(POST_ID, title=f'{word} synthesis'))
    _save(store, _record('ijklmnop-other', title=f'{word} lesson'))
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert _ids(reader, PostFilters(text=query)) == [POST_ID]


@pytest.mark.parametrize(
    ('title', 'query'),
    [
        pytest.param('\ue000lesson', '\ue000les', id='private-use-prefix'),
        pytest.param('alphabet', '\u0301alpha', id='leading-accent'),
        pytest.param('alphabet', '\u0301', id='accent-only'),
        pytest.param('alphabet', '\u034f', id='grapheme-joiner-only'),
    ],
)
def test_search_respects_sqlite_unicode_token_categories(
    root: Path, title: str, query: str
) -> None:
    store = JsonPostStore(root)
    _save(store, _record(POST_ID, title=title))
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert _ids(reader, PostFilters(text=query)) == [POST_ID]


@pytest.mark.parametrize(
    'separator',
    [
        pytest.param('\u034f', id='nonspacing-grapheme-joiner'),
        pytest.param('\u20dd', id='enclosing-circle'),
        pytest.param('\u093f', id='spacing-vowel-sign'),
    ],
)
def test_search_separator_marks_keep_independent_prefixes(
    root: Path, separator: str
) -> None:
    store = JsonPostStore(root)
    _save(store, _record(POST_ID, title='alphabet intervening betatron'))
    _save(store, _record('ijklmnop-other', title='alphabet only'))
    reader = JsonLibraryReader(root)
    reader.prepare()
    assert _ids(reader, PostFilters(text=f'alpha{separator}beta')) == [POST_ID]
