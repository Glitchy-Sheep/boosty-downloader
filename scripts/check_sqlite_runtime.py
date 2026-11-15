"""Report and verify the actual Python SQLite runtime used by CI."""

import sqlite3
import sys
from contextlib import closing
from platform import python_version

from boosty_downloader.infrastructure.library._db_runtime import (
    require_supported_sqlite,
)


def main() -> None:
    """Fail setup when the loaded SQLite lacks verified WAL fixes or FTS5."""
    print(f'Python: {python_version()} ({sys.executable})')
    print(f'SQLite: {sqlite3.sqlite_version}')
    with closing(sqlite3.connect(':memory:')) as connection:
        source_id = connection.execute('SELECT sqlite_source_id()').fetchone()[0]
        options = [row[0] for row in connection.execute('PRAGMA compile_options')]
    print(f'SQLite source: {source_id}')
    print(f'SQLite compile options: {", ".join(options)}')
    require_supported_sqlite()
    print('FTS5: available (in-memory virtual table probe)')
    print('Primary-library SQLite runtime verified')


if __name__ == '__main__':
    main()
