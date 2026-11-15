import sqlite3
import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import Mock

import pytest

from boosty_downloader.infrastructure.library import _db_runtime
from boosty_downloader.infrastructure.library._db_errors import (
    UnsupportedLibraryDatabaseError,
)


@pytest.fixture(autouse=True)
def _clear_probe_cache() -> Generator[None, None, None]:
    _db_runtime._require_fts5.cache_clear()  # pyright: ignore[reportPrivateUsage]
    yield
    _db_runtime._require_fts5.cache_clear()  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    'version',
    [
        '3.44.6',
        '3.44.7',
        '3.50.7',
        '3.50.8',
        '3.51.3',
        '3.51.4',
        '3.52.0',
        '3.53.4',
        '4.0.0',
    ],
)
def test_verified_release_families_reach_fts_probe(
    monkeypatch: pytest.MonkeyPatch, version: str
):
    monkeypatch.setattr(
        sqlite3, 'sqlite_version_info', tuple(map(int, version.split('.')))
    )
    probe = Mock()
    monkeypatch.setattr(_db_runtime, '_require_fts5', probe)
    _db_runtime.require_supported_sqlite()
    probe.assert_called_once_with()


@pytest.mark.parametrize(
    'version',
    [
        '3.43.99',
        '3.44.5',
        '3.45.9',
        '3.46.9',
        '3.47.9',
        '3.48.9',
        '3.49.9',
        '3.50.6',
        '3.51.0',
        '3.51.1',
        '3.51.2',
    ],
)
def test_unverified_release_is_rejected_before_any_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sqlite3, 'sqlite_version_info', tuple(map(int, version.split('.')))
    )
    monkeypatch.setattr(sqlite3, 'sqlite_version', version)
    connect = Mock(side_effect=AssertionError('No connection is allowed'))
    monkeypatch.setattr(sqlite3, 'connect', connect)
    with pytest.raises(UnsupportedLibraryDatabaseError, match='unverified') as failure:
        _db_runtime.require_supported_sqlite()
    assert sys.executable in str(failure.value)
    assert f'SQLite: {version}' in str(failure.value)
    assert 'Update or recreate the Python environment' in str(failure.value)
    connect.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_successful_fts_probe_uses_only_memory_and_closes_its_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    actual_connect = sqlite3.connect
    connections: list[sqlite3.Connection] = []

    def connect_memory(database: str) -> sqlite3.Connection:
        assert database == ':memory:'
        connection = actual_connect(database)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, 'connect', connect_memory)
    _db_runtime.require_supported_sqlite()
    _db_runtime.require_supported_sqlite()
    assert len(connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connections[0].execute('SELECT 1')
    assert list(tmp_path.iterdir()) == []


def test_failed_fts_probe_is_not_cached_and_closes_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    actual_connect = sqlite3.connect
    connections: list[sqlite3.Connection] = []

    def connect_without_fts(database: str) -> sqlite3.Connection:
        assert database == ':memory:'
        connection = actual_connect(database)
        connection.set_authorizer(_deny_query)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, 'connect', connect_without_fts)
    for _ in range(2):
        with pytest.raises(UnsupportedLibraryDatabaseError, match='FTS5 probe failed'):
            _db_runtime.require_supported_sqlite()
    assert len(connections) == 2
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            connection.execute('SELECT 1')
    assert list(tmp_path.iterdir()) == []


def _deny_query(*_arguments: int | str | None) -> int:
    return sqlite3.SQLITE_DENY


def test_missing_fts_module_reports_runtime_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
):
    connection = Mock(spec=sqlite3.Connection)
    missing_fts = sqlite3.OperationalError('no such module: fts5')
    connection.execute.side_effect = missing_fts
    connect = Mock(return_value=connection)
    monkeypatch.setattr(sqlite3, 'connect', connect)
    with pytest.raises(UnsupportedLibraryDatabaseError, match='FTS5') as failure:
        _db_runtime.require_supported_sqlite()
    assert failure.value.__cause__ is missing_fts
    assert sys.executable in str(failure.value)
    assert f'SQLite: {sqlite3.sqlite_version}' in str(failure.value)
    connect.assert_called_once_with(':memory:')
    connection.close.assert_called_once_with()


def test_cached_fts_success_does_not_bypass_version_validation(
    monkeypatch: pytest.MonkeyPatch,
):
    _db_runtime.require_supported_sqlite()
    monkeypatch.setattr(sqlite3, 'sqlite_version_info', (3, 50, 6))
    with pytest.raises(UnsupportedLibraryDatabaseError, match='unverified'):
        _db_runtime.require_supported_sqlite()
