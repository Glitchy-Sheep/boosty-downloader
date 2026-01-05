"""SQLAlchemy models for the post caching layer."""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from boosty_downloader.src.application.filtering import DownloadContentTypeFilter


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


class PostCacheEntryModel(Base):
    """SQLite table structure for caching post download state."""

    __tablename__ = 'post_cache'

    post_uuid: Mapped[str] = mapped_column(String, primary_key=True)

    # Flags to see which parts of the posts were downloaded and which are not.
    files_downloaded: Mapped[bool] = mapped_column(default=False, nullable=False)
    post_content_downloaded: Mapped[bool] = mapped_column(default=False, nullable=False)
    external_videos_downloaded: Mapped[bool] = mapped_column(
        default=False, nullable=False
    )
    boosty_videos_downloaded: Mapped[bool] = mapped_column(
        default=False, nullable=False
    )
    audio_downloaded: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Timestamp of the last update of the post.
    # Useful to determine if the post is outdated and needs to be re-downloaded
    # even if some parts were downloaded before.
    #
    # Should be in ISO 8601 format (e.g., "2023-10-01T12:00:00Z")
    # because SQLite does not have a native tz-aware datetime type.
    last_updated_timestamp: Mapped[str] = mapped_column(String, nullable=False)

    def is_downloaded(self, content_type: DownloadContentTypeFilter) -> bool:
        """Check if a specific content type has been downloaded."""
        match content_type:
            case DownloadContentTypeFilter.files:
                return self.files_downloaded
            case DownloadContentTypeFilter.post_content:
                return self.post_content_downloaded
            case DownloadContentTypeFilter.external_videos:
                return self.external_videos_downloaded
            case DownloadContentTypeFilter.boosty_videos:
                return self.boosty_videos_downloaded
            case DownloadContentTypeFilter.audio:
                return self.audio_downloaded

    def mark_downloaded(
        self, content_types: Iterable[DownloadContentTypeFilter]
    ) -> None:
        """Mark the given content types as downloaded."""
        for content_type in content_types:
            match content_type:
                case DownloadContentTypeFilter.files:
                    self.files_downloaded = True
                case DownloadContentTypeFilter.post_content:
                    self.post_content_downloaded = True
                case DownloadContentTypeFilter.external_videos:
                    self.external_videos_downloaded = True
                case DownloadContentTypeFilter.boosty_videos:
                    self.boosty_videos_downloaded = True
                case DownloadContentTypeFilter.audio:
                    self.audio_downloaded = True

    @classmethod
    def create_new(
        cls,
        post_uuid: str,
        updated_at: datetime,
        downloaded: Iterable[DownloadContentTypeFilter],
    ) -> 'PostCacheEntryModel':
        """Create a new cache entry with the given downloaded content types."""
        downloaded_set = set(downloaded)
        return cls(
            post_uuid=post_uuid,
            last_updated_timestamp=updated_at.isoformat(),
            files_downloaded=DownloadContentTypeFilter.files in downloaded_set,
            post_content_downloaded=DownloadContentTypeFilter.post_content
            in downloaded_set,
            external_videos_downloaded=DownloadContentTypeFilter.external_videos
            in downloaded_set,
            boosty_videos_downloaded=DownloadContentTypeFilter.boosty_videos
            in downloaded_set,
            audio_downloaded=DownloadContentTypeFilter.audio in downloaded_set,
        )
