"""Module with post caching logic for skipping already downloaded posts."""

import sqlite3
from contextlib import suppress
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
                post_id TEXT PRIMARY KEY,
                title TEXT,
                last_updated TEXT
            )
        """)
        self.conn.commit()

    def add_post_cache(self, post_id: str, title: str, updated_at: datetime) -> None:
        """Add post to cache with post_id, title and updated_at"""
        updated_at_str: str = updated_at.strftime('%Y-%m-%dT%H:%M:%S')
        self.cursor.execute(
            """
            INSERT OR REPLACE INTO post_cache (post_id, title, last_updated)
            VALUES (?, ?, ?)
        """,
            (post_id, title, updated_at_str),
        )
        self.conn.commit()

    def has_same_post(
        self,
        post_id: str,
        current_title: str,
        updated_at: datetime,
        current_folder_name: str,
    ) -> bool:
        """
        Check if post with the same post_id and updated_at exists.

        This method only checks the cache and does not perform any folder operations.
        Use ensure_folder_name_matches() separately if folder rename is needed.
        """
        # Check if post exists in the cache
        self.cursor.execute(
            """
            SELECT title, last_updated FROM post_cache WHERE post_id = ?
        """,
            (post_id,),
        )

        result: tuple[str, str] | None = self.cursor.fetchone()
        if not result:
            # Post not in cache
            return False

        cached_title, stored_updated_at = result

        # If title has changed, post needs to be re-downloaded
        if cached_title != current_title:
            return False

        # Check if the current folder exists
        current_post_path = self.destination / current_folder_name
        if not current_post_path.exists():
            # Folder doesn't exist - remove from cache and return False
            self.cleanup_cache_by_id(post_id)
            return False

        # Compare updated_at to see if post needs to be re-downloaded
        updated_at_str: str = updated_at.strftime('%Y-%m-%dT%H:%M:%S')
        return updated_at_str == stored_updated_at

    def ensure_folder_name_matches(
        self,
        post_id: str,
        current_title: str,
        created_at: datetime,
    ) -> None:
        """
        Ensure that the folder name matches the current post title.

        If the post title has changed since last cache, rename the folder
        to match the new title.
        """
        # Check if post exists in the cache
        self.cursor.execute(
            """
            SELECT title FROM post_cache WHERE post_id = ?
        """,
            (post_id,),
        )

        result: tuple[str,] | None = self.cursor.fetchone()
        if not result:
            # Post not in cache - no rename needed
            return

        (cached_title,) = result

        # Check if title has changed and we need to rename folder
        if cached_title != current_title:
            cached_folder_name = f'{created_at.date()} - {cached_title}'
            current_folder_name = f'{created_at.date()} - {current_title}'

            self._rename_post_folder_if_needed(
                old_folder_name=cached_folder_name,
                new_folder_name=current_folder_name,
            )

    def _rename_post_folder_if_needed(
        self,
        old_folder_name: str,
        new_folder_name: str,
    ) -> None:
        """Rename post folder if title has changed to maintain cache-folder link."""
        if old_folder_name == new_folder_name:
            return  # No rename needed

        old_path = self.destination / old_folder_name
        new_path = self.destination / new_folder_name

        if old_path.exists() and not new_path.exists():
            with suppress(OSError):
                # Continue anyway - the post will be re-downloaded to new location
                old_path.rename(new_path)
        # If old_path doesn't exist, no rename is needed

    def cleanup_cache_by_id(self, post_id: str) -> None:
        """Clean cache by post_id if post doesn't exist"""
        self.cursor.execute(
            """
            DELETE FROM post_cache WHERE post_id = ?
        """,
            (post_id,),
        )
        self.conn.commit()

    def cleanup_cache(self, title: str) -> None:
        """Clean cache if post doesn't exist (kept for backward compatibility)"""
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
