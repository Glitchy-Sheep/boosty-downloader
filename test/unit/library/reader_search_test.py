"""Exact FTS tokenization and plain original-text contexts for library search."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.domain.library import PostFilters, SearchMatch, SearchRun
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.library._reader_search import search_expression
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path: Path) -> JsonPostStore:
    initialize_library(tmp_path)
    return JsonPostStore(tmp_path)


def _save(
    store: JsonPostStore, title: str, body: str = '', *, post_id: str = 'abcdefgh-one'
) -> None:
    metadata = PostMetadata(
        post_id, 'writer', f'https://boosty.to/writer/posts/{post_id}', title, NOW, NOW
    )
    record = StoredPost(
        metadata,
        PostSync(NOW, NOW),
        [TextBlock([PostDataChunkText.TextFragment(body)])],
    )
    store.save_post(store.choose_post_folder(metadata), record)


def _reader(root: Path) -> JsonLibraryReader:
    reader = JsonLibraryReader(root)
    reader.prepare()
    return reader


def _match(reader: JsonLibraryReader, query: str) -> SearchMatch:
    result = reader.list_posts('writer', PostFilters(text=query))
    assert result.total == 1
    match = result.rows[0].match
    assert match is not None
    return match


def _matched(runs: tuple[SearchRun, ...]) -> list[str]:
    return [run.text for run in runs if run.matched]


@pytest.mark.parametrize(
    ('document', 'query'),
    [
        ('a\u1ab0b', 'a\u1ab0b'),
        ('\U00011315\U0001133e\U00011324', '\U00011315\U0001133e\U00011324'),
        ('Café', 'cafe'),
        ('Cafe\u0301', 'CAFÉ'),
        ('мо\u0301й урок', 'мой'),
        ('Всё', 'все'),
        ('Всё', 'всё'),
        ('Шейдеры', 'шейд'),
        ('İßﬃ', 'İßﬃ'),
        ('Alpha_beta@Gamma', 'Alpha_beta@Gamma'),
        ('a b', 'a\x00b'),
    ],
)
def test_query_uses_same_unicode61_tokenizer_as_index(
    tmp_path: Path, store: JsonPostStore, document: str, query: str
) -> None:
    _save(store, document)
    match = _match(_reader(tmp_path), query)
    assert ''.join(run.text for run in match.title) == document
    assert _matched(match.title)
    assert match.text is None


@pytest.mark.parametrize('character', ['x', 'я', '漢', '\U00011315'])
def test_query_longer_than_fts_token_byte_limit_keeps_a_valid_matching_prefix(
    tmp_path: Path, store: JsonPostStore, character: str
) -> None:
    word = 'a' + character * 33000
    _save(store, 'Long word', word)
    match = _match(_reader(tmp_path), word)
    assert match.text is not None
    assert _matched(match.text) == [word]
    assert search_expression(word).encode('utf-8')


@pytest.mark.parametrize(
    'query', ['"', '*', '!?-___', '\u0301', '😀', '\x02\x03', ' \t\n']
)
def test_token_free_query_is_unfiltered_without_match_context(
    tmp_path: Path, store: JsonPostStore, query: str
) -> None:
    _save(store, 'Ordinary post')
    result = _reader(tmp_path).list_posts('writer', PostFilters(text=query))
    assert result.total == 1
    assert result.rows[0].match is None
    assert search_expression(query) == ''


@pytest.mark.parametrize(
    'query',
    [
        'alpha OR beta',
        '"alpha" AND beta*',
        'alpha NOT beta',
        'alpha NEAR beta',
        'title:alpha',
    ],
)
def test_operators_and_column_names_are_literal_required_prefix_terms(
    tmp_path: Path, store: JsonPostStore, query: str
) -> None:
    _save(store, 'alpha AND OR NOT NEAR beta title')
    _save(store, 'alpha beta', post_id='ijklmnop-other')
    match = _match(_reader(tmp_path), query)
    assert len(_matched(match.title)) >= 2


def test_repeated_terms_are_deduplicated_and_combined_with_and() -> None:
    assert search_expression('BETA alpha ALPHA') == '"alpha"* AND "beta"*'


def test_all_terms_can_match_across_title_and_body_in_either_order(
    tmp_path: Path, store: JsonPostStore
) -> None:
    _save(store, 'Alphabet', 'Zoom beta')
    reader = _reader(tmp_path)
    match = _match(reader, 'bet alph')
    assert _matched(match.title) == ['Alphabet']
    assert match.text is not None
    assert _matched(match.text) == ['beta']
    assert reader.list_posts('writer', PostFilters(text='alpha absent')).total == 0


def test_cyrillic_short_i_remains_distinct(
    tmp_path: Path, store: JsonPostStore
) -> None:
    _save(store, 'Мой урок')
    _save(store, 'Мои уроки', post_id='ijklmnop-other')
    reader = _reader(tmp_path)
    assert _matched(_match(reader, 'мой').title) == ['Мой']
    assert _matched(_match(reader, 'мои').title) == ['Мои']


def test_original_accents_yo_and_marker_replacements_survive_highlights(
    tmp_path: Path, store: JsonPostStore
) -> None:
    _save(store, '\x02Всё\x03 и Café', 'Всё мо\u0301ё café\x02tail\x03')
    match = _match(_reader(tmp_path), 'все cafe')
    assert match.title == (
        SearchRun(' ', matched=False),
        SearchRun('Всё', matched=True),
        SearchRun('  и ', matched=False),
        SearchRun('Café', matched=True),
    )
    assert match.text is not None
    assert ''.join(run.text for run in match.text) == 'Всё мо\u0301ё café tail'
    assert _matched(match.text) == ['Всё', 'café']


def test_script_text_is_plain_and_whole_prefix_hits_are_marked(
    tmp_path: Path, store: JsonPostStore
) -> None:
    body = '<script>alert("lesson");</script> Shader lessons'
    _save(store, 'Title', body)
    match = _match(_reader(tmp_path), 'less')
    assert match.text is not None
    assert ''.join(run.text for run in match.text) == body
    assert _matched(match.text) == ['lesson', 'lessons']
    assert match.title == (SearchRun('Title', matched=False),)


def test_body_context_is_cut_at_word_boundaries_around_first_hit(
    tmp_path: Path, store: JsonPostStore
) -> None:
    body = 'before ' * 40 + 'Needle ' + 'after ' * 50 + 'needle'
    _save(store, 'Title', body)
    match = _match(_reader(tmp_path), 'need')
    assert match.text is not None
    snippet = ''.join(run.text for run in match.text)
    assert snippet.startswith('…before ')
    assert snippet.endswith(' after…')
    assert _matched(match.text) == ['Needle']
    assert len(snippet) < 220


def test_long_match_at_context_boundary_is_never_split(
    tmp_path: Path, store: JsonPostStore
) -> None:
    long_word = 'needle' + 'x' * 250
    _save(store, 'Title', 'needle,' + long_word + ' tail ' * 30)
    match = _match(_reader(tmp_path), 'needle')
    assert match.text is not None
    assert _matched(match.text) == ['needle', long_word]
    assert ''.join(run.text for run in match.text).endswith(long_word + '…')


@pytest.mark.parametrize('query', ['a', 'b', 'a b'])
def test_nul_controls_preserve_complete_title_and_correct_hits(
    tmp_path: Path, store: JsonPostStore, query: str
) -> None:
    _save(store, 'a\x00b')
    match = _match(_reader(tmp_path), query)
    assert ''.join(run.text for run in match.title) == 'a b'
    assert _matched(match.title) == query.split()


def test_nul_before_body_hit_preserves_unmatched_words_and_canonical_body(
    tmp_path: Path, store: JsonPostStore
) -> None:
    body = 'abc\x00xneedle needle tail'
    _save(store, 'Title', body)
    reader = _reader(tmp_path)
    match = _match(reader, 'needle')
    assert match.text is not None
    assert ''.join(run.text for run in match.text) == 'abc xneedle needle tail'
    assert _matched(match.text) == ['needle']
    detail = reader.post('writer', 'abcdefgh-one')
    assert detail is not None
    assert detail.record is not None
    assert detail.record.blocks == [TextBlock([PostDataChunkText.TextFragment(body)])]
