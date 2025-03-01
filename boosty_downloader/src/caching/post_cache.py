"""Module with post caching logic for skipping already downloaded posts."""

import sqlite3
from datetime import datetime
from pathlib import Path


class PostCache:
    """
    Cache posts for not downloading them again.

    It uses SQLite database for storing the data.
    """

    DEFAULT_CACHE_FILENAME = 'post_cache.db'

    def __init__(self, destination: Path) -> None:
        """
        Initialize the PostCache with the provided destination folder.

        If the database doesn't exist, it will be created automatically.
        """
        self.destination = destination
        self.db_file: Path = self.destination / self.DEFAULT_CACHE_FILENAME
        self.db_file.parent.mkdir(parents=True, exist_ok=True)

        if not self.db_file.exists():
            self.db_file.touch()

        self.conn: sqlite3.Connection = sqlite3.connect(self.db_file)
        self.cursor: sqlite3.Cursor = self.conn.cursor()
        self._create_table()

    def _create_table(self) -> None:
        """Create table if not exists"""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS post_cache (
                title TEXT PRIMARY KEY,
                last_updated TEXT
            )
        """)
        self.conn.commit()

    def add_post_cache(self, title: str, updated_at: datetime) -> None:
        """Add post to cache with updated_at"""
        updated_at_str: str = updated_at.strftime('%Y-%m-%dT%H:%M:%S')
        self.cursor.execute(
            """
            INSERT OR REPLACE INTO post_cache (title, last_updated)
            VALUES (?, ?)
        """,
            (title, updated_at_str),
        )
        self.conn.commit()

    def has_same_post(
        self,
        title: str,
        updated_at: datetime,
    ) -> bool:
        """Check if post with the same title and updated_at exists"""
        # Check if the post folder exists
        post_path = self.destination / title
        if not post_path.exists():
            # If post doesn't exist in folder, remove it from cache and return False
            self.cleanup_cache(title)
            return False

        # Check if post exists in the cache
        self.cursor.execute(
            """
            SELECT last_updated FROM post_cache WHERE title = ?
        """,
            (title,),
        )

        # result is either None or a tuple with one string element (the last_updated value)
        result: tuple[str] | None = self.cursor.fetchone()

        if not result:
            return False

        # Convert updated_at (datetime) to string to compare with stored updated_at
        stored_updated_at: str = result[0]
        updated_at_str: str = updated_at.strftime(
            '%Y-%m-%dT%H:%M:%S',
        )  # Convert updated_at to string

        # Compare the string representations
        return updated_at_str == stored_updated_at

    def cleanup_cache(self, title: str) -> None:
        """Clean cache if post doesn't exist"""
        self.cursor.execute(
            """
            DELETE FROM post_cache WHERE title = ?
        """,
            (title,),
        )
        self.conn.commit()

    def close(self) -> None:
        """Close connection to database"""
        self.conn.close()
