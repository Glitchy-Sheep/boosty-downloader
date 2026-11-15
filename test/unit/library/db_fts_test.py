from pathlib import Path

import pytest
from sqlalchemy import select, text
from support.library_db import saved_post

from boosty_downloader.infrastructure.library._db_models import DbAuthor, DbPost
from boosty_downloader.infrastructure.library._reader_search import search_expression
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


def _matches(database: LibraryDatabase, query: str) -> list[int]:
    with database.transaction() as session:
        return list(
            session.execute(
                text(
                    'SELECT rowid FROM posts_fts WHERE posts_fts MATCH :query ORDER BY rowid'
                ),
                {'query': search_expression(query)},
            ).scalars()
        )


def test_fts_tracks_insert_title_body_changes_and_delete_atomically(tmp_path: Path):
    with LibraryDatabase.create(tmp_path.resolve() / 'library.db') as database:
        with database.transaction() as session:
            session.add(DbAuthor(author='alice'))
            session.flush()
            post = saved_post(title='Ёлка café', body='Сохранённый текст')
            session.add(post)
            session.flush()
            row_id = post.id
        assert _matches(database, 'ЕЛКА CAFE') == [row_id]
        assert _matches(database, 'сохраненный') == [row_id]
        with database.transaction() as session:
            post = session.scalars(select(DbPost)).one()
            post.title = 'Звёздный сад'
            post.body_text = 'Новый материал'
        assert _matches(database, 'ЕЛКА') == []
        assert _matches(database, 'ЗВЕЗДНЫЙ МАТЕР') == [row_id]
        with database.transaction() as session:
            session.delete(session.scalars(select(DbPost)).one())
        assert _matches(database, 'ЗВЕЗДНЫЙ') == []


def test_fts_preserves_literal_prefixes_punctuation_and_control_offsets(tmp_path: Path):
    with LibraryDatabase.create(tmp_path.resolve() / 'library.db') as database:
        with database.transaction() as session:
            session.add(DbAuthor(author='alice'))
            session.flush()
            post = saved_post(
                title='OR character* "quote"', body='before\0AFTER\x02middle\x03end'
            )
            session.add(post)
            session.flush()
            row_id = post.id
        assert _matches(database, 'OR character*') == [row_id]
        assert _matches(database, '"quote"') == [row_id]
        assert _matches(database, 'AFTER middle') == [row_id]
        with database.transaction() as session:
            post = session.scalars(select(DbPost)).one()
            assert post.body_text == 'before\0AFTER\x02middle\x03end'
            assert post.body_search == 'before AFTER middle end'
            assert len(post.body_text) == len(post.body_search)


def test_fts_and_canonical_row_roll_back_together(tmp_path: Path):
    with LibraryDatabase.create(tmp_path.resolve() / 'library.db') as database:
        with database.transaction() as session:
            session.add(DbAuthor(author='alice'))
            session.flush()
            session.add(saved_post(title='Original'))
        with pytest.raises(RuntimeError, match='rollback'):
            _replace_and_fail(database)
        assert _matches(database, 'Replacement') == []
        assert _matches(database, 'Original') == [1]


def _replace_and_fail(database: LibraryDatabase) -> None:
    with database.transaction() as session:
        post = session.scalars(select(DbPost)).one()
        post.title = 'Replacement'
        session.flush()
        assert (
            session.execute(
                text("SELECT rowid FROM posts_fts WHERE posts_fts MATCH 'replacement'")
            ).scalar_one()
            == post.id
        )
        message = 'rollback'
        raise RuntimeError(message)
