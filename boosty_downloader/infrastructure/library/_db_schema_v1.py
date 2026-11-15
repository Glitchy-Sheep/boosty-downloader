"""Frozen first primary schema; later model changes do not alter this migration."""

from typing import Final

SCHEMA_V1: Final = (
    """CREATE TABLE meta (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        schema_version INTEGER NOT NULL,
        library_id TEXT NOT NULL
    )""",
    """CREATE TABLE authors (
        author TEXT PRIMARY KEY NOT NULL,
        title TEXT, owner_name TEXT, description TEXT,
        avatar_path TEXT, cover_path TEXT, synced_at DATETIME,
        remote_post_count INTEGER CHECK (remote_post_count >= 0)
    )""",
    """CREATE TABLE posts (
        id INTEGER PRIMARY KEY,
        author TEXT NOT NULL REFERENCES authors(author) ON DELETE CASCADE,
        post_id TEXT NOT NULL, folder TEXT, url TEXT NOT NULL, title TEXT NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, published_at DATETIME,
        access TEXT NOT NULL CHECK (access IN ('open', 'locked')),
        tier TEXT, tier_price_rub FLOAT CHECK (tier_price_rub >= 0),
        post_price_rub FLOAT CHECK (post_price_rub >= 0),
        likes INTEGER NOT NULL CHECK (likes >= 0),
        comments INTEGER NOT NULL CHECK (comments >= 0),
        tags JSON NOT NULL, content_counters JSON NOT NULL,
        saved_metadata TEXT, blocks_json TEXT, origin TEXT CHECK (origin = 'api'),
        first_downloaded_at DATETIME, synced_at DATETIME,
        page_template INTEGER CHECK (page_template >= 0),
        locked_synced_at DATETIME, teaser_path TEXT, teaser_thumbnail_path TEXT,
        body_text TEXT NOT NULL,
        UNIQUE (author, post_id), UNIQUE (id, author),
        CHECK (
            (saved_metadata IS NULL AND folder IS NULL AND blocks_json IS NULL
             AND origin IS NULL AND first_downloaded_at IS NULL AND synced_at IS NULL
             AND page_template IS NULL)
            OR
            (saved_metadata IS NOT NULL AND folder IS NOT NULL AND blocks_json IS NOT NULL
             AND origin = 'api' AND first_downloaded_at IS NOT NULL AND synced_at IS NOT NULL)
        ),
        CHECK (
            (access = 'locked' AND locked_synced_at IS NOT NULL)
            OR (access = 'open' AND locked_synced_at IS NULL AND saved_metadata IS NOT NULL)
        )
    )""",
    """CREATE TABLE media (
        post_row_id INTEGER NOT NULL, media_id TEXT NOT NULL, author TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('image', 'file', 'audio', 'boosty_video', 'external_video')),
        status TEXT NOT NULL CHECK (status IN ('pending', 'downloaded', 'failed', 'unavailable', 'deleted')),
        position INTEGER NOT NULL CHECK (position >= 0),
        path TEXT, thumbnail_path TEXT, preview_path TEXT,
        title TEXT, filename TEXT, artist TEXT,
        size INTEGER CHECK (size >= 0), duration FLOAT CHECK (duration >= 0),
        width INTEGER CHECK (width >= 0), height INTEGER CHECK (height >= 0),
        error TEXT, added_at DATETIME NOT NULL, removed_at DATETIME,
        PRIMARY KEY (post_row_id, media_id),
        FOREIGN KEY (post_row_id, author) REFERENCES posts(id, author) ON DELETE CASCADE,
        CHECK (status != 'downloaded' OR (path IS NOT NULL AND size IS NOT NULL))
    )""",
    """CREATE TABLE post_tags (
        post_row_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
        tag TEXT NOT NULL, PRIMARY KEY (post_row_id, tag)
    )""",
    """CREATE TABLE marks (
        post_row_id INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
        seen_at DATETIME, favorite BOOLEAN NOT NULL
    )""",
    """CREATE TABLE media_marks (
        post_row_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
        media_id TEXT NOT NULL, position FLOAT NOT NULL CHECK (position >= 0),
        finished_at DATETIME, PRIMARY KEY (post_row_id, media_id)
    )""",
    'CREATE INDEX ix_posts_author_created ON posts(author, created_at)',
    'CREATE INDEX ix_posts_author_access ON posts(author, access)',
    'CREATE INDEX ix_posts_author_folder ON posts(author, folder)',
    'CREATE INDEX ix_media_storage ON media(status, author, kind, size)',
    'CREATE INDEX ix_media_post_order ON media(post_row_id, position)',
    'CREATE INDEX ix_post_tags_tag_post ON post_tags(tag, post_row_id)',
)
