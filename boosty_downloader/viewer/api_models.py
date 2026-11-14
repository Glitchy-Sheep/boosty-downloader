"""Validated JSON values shared by the viewer API and generated client types."""

from typing import Annotated, Final, Literal, TypeAlias

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    StrictBool,
)

PostAccess: TypeAlias = Literal['open', 'locked']
SortOrder: TypeAlias = Literal['newest', 'oldest']
MediaKind: TypeAlias = Literal['images', 'videos', 'files', 'audio']
MediaView: TypeAlias = Literal['all', 'images', 'videos', 'audio', 'files']
OpenerSystem: TypeAlias = Literal['macos', 'windows', 'linux', 'android']
FileType: TypeAlias = Literal[
    'pdf',
    'document',
    'book',
    'sheet',
    'slides',
    'image',
    'audio',
    'video',
    'archive',
    'model',
    'code',
    'font',
    'program',
    'script',
    'other',
]
NonNegativeNumber: TypeAlias = Annotated[
    float, Field(strict=True, ge=0, allow_inf_nan=False)
]

ERROR_NOT_FOUND: Final = 'not_found'
ERROR_HOST_NOT_ALLOWED: Final = 'host_not_allowed'
ERROR_WRITE_NOT_ALLOWED: Final = 'write_not_allowed'


class _APIModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra='forbid',
        json_schema_serialization_defaults_required=True,
    )


class ErrorBody(_APIModel):
    """A stable machine code and a user-facing explanation."""

    code: str
    message: str


class ErrorResponse(_APIModel):
    """The JSON envelope for an unsuccessful viewer request."""

    error: ErrorBody


class MediaCounts(_APIModel):
    """Counts of current pieces, combining both video sources."""

    images: NonNegativeInt = 0
    videos: NonNegativeInt = 0
    files: NonNegativeInt = 0
    audio: NonNegativeInt = 0


class MediaStorage(_APIModel):
    """Downloaded bytes, including retained copies removed from a post."""

    images: NonNegativeInt = 0
    videos: NonNegativeInt = 0
    files: NonNegativeInt = 0
    audio: NonNegativeInt = 0


class Author(_APIModel):
    """An author's display information and complete local library totals."""

    name: str
    title: str
    description: str
    avatar_url: str | None = None
    cover_url: str | None = None
    posts: NonNegativeInt = 0
    locked: NonNegativeInt = 0
    unseen: NonNegativeInt = 0
    favorites: NonNegativeInt = 0
    storage: MediaStorage = Field(default_factory=MediaStorage)


class SearchRun(_APIModel):
    """A plain-text fragment and whether it matched the search."""

    text: str
    matched: bool


class SearchMatch(_APIModel):
    """Search highlights; a null body means only the title matched."""

    title: list[SearchRun] = Field(default_factory=list[SearchRun])
    text: list[SearchRun] | None = None


class PostRow(_APIModel):
    """A compact post listing without its full body or media inventory."""

    id: str
    title: str
    created_at: AwareDatetime
    access: PostAccess
    tier: str | None = None
    cover_path: str | None = Field(
        default=None, description='Author-relative cover path.'
    )
    counts: MediaCounts = Field(default_factory=MediaCounts)
    missing_media: NonNegativeInt = 0
    seen: bool = False
    favorite: bool = False
    updated: bool = False
    match: SearchMatch | None = None


class MonthCount(_APIModel):
    """Number of filtered posts in one UTC calendar month."""

    month: Annotated[str, Field(pattern=r'^[0-9]{4}-(0[1-9]|1[0-2])$')]
    count: NonNegativeInt


class PostList(_APIModel):
    """Rows, month counts and a total for the same filtered result."""

    rows: list[PostRow] = Field(default_factory=list[PostRow])
    months: list[MonthCount] = Field(default_factory=list[MonthCount])
    total: NonNegativeInt = 0


class TagCount(_APIModel):
    """Number of distinct posts carrying an exact stored tag."""

    tag: str
    count: NonNegativeInt


class MediaItem(_APIModel):
    """A downloaded current or retained media file, without repeated post data."""

    id: str = Field(description='Opaque identity containing the post and media piece.')
    post_id: str
    created_at: AwareDatetime
    kind: MediaKind
    path: str = Field(description='Author-relative file path.')
    thumb_path: str | None = Field(
        default=None, description='Author-relative thumbnail path.'
    )
    title: str | None = None
    filename: str | None = None
    artist: str | None = None
    size: NonNegativeInt = Field(description='Downloaded file size in bytes.')
    width: NonNegativeInt | None = None
    height: NonNegativeInt | None = None
    duration_s: NonNegativeNumber | None = None
    position_s: NonNegativeNumber | None = None
    finished: bool = False
    file_type: FileType
    removed: bool = False


class PostDetail(PostRow):
    """A post's retained body and files, independent of current access."""

    tags: list[str] = Field(default_factory=list[str])
    tier_price_rub: NonNegativeNumber | None = None
    post_price_rub: NonNegativeNumber | None = None
    boosty_url: str
    body_html: str
    media: list[MediaItem] = Field(default_factory=list[MediaItem])
    has_folder: bool


class PostFilters(_APIModel):
    """Normalized filters, also used to choose posts for bulk marks."""

    q: str = ''
    kind: MediaKind | None = None
    unseen: StrictBool = False
    fav: StrictBool = False
    tag: Annotated[str, Field(min_length=1)] | None = None
    locked: StrictBool = False
    incomplete: StrictBool = False
    order: SortOrder = 'newest'


class SeenMarkRequest(_APIModel):
    """Change only the seen mark on one post."""

    seen: StrictBool


class FavoriteMarkRequest(_APIModel):
    """Change only the favorite mark on one post."""

    favorite: StrictBool


MarkRequest: TypeAlias = SeenMarkRequest | FavoriteMarkRequest


class MarkResult(_APIModel):
    """The refreshed post and author after one mark changes."""

    post: PostRow
    author: Author


class BulkMarksRequest(_APIModel):
    """Apply a seen value to all posts selected by normalized filters."""

    seen: StrictBool
    filters: PostFilters


class BulkMarksResult(_APIModel):
    """Number of posts whose seen mark changed."""

    count: NonNegativeInt


class BulkMarksProgressResponse(_APIModel):
    """Progress of the active bulk; the POST response reports its final outcome."""

    active: bool
    total: NonNegativeInt | None = None
    completed: NonNegativeInt = 0
    changed: NonNegativeInt = 0


class MediaFilters(_APIModel):
    """Normalized filters for an author's media screen."""

    view: MediaView = 'all'
    order: SortOrder = 'newest'
    unseen: StrictBool = False
    fav: StrictBool = False


class MediaViewCounts(_APIModel):
    """Downloaded media totals for every media-screen category."""

    all: NonNegativeInt = 0
    images: NonNegativeInt = 0
    videos: NonNegativeInt = 0
    audio: NonNegativeInt = 0
    files: NonNegativeInt = 0


class MediaPost(_APIModel):
    """Display data shared by all media belonging to one post."""

    title: str
    cover_path: str | None = Field(
        default=None, description='Author-relative cover path.'
    )
    seen: bool = False
    favorite: bool = False


class MediaPage(_APIModel):
    """Media with shared post data, category totals and missing-file count."""

    items: list[MediaItem] = Field(default_factory=list[MediaItem])
    posts: dict[str, MediaPost] = Field(default_factory=dict[str, MediaPost])
    counts: MediaViewCounts = Field(default_factory=MediaViewCounts)
    missing: NonNegativeInt = 0


class PositionRequest(_APIModel):
    """Playback position and duration in finite, nonnegative seconds."""

    seconds: NonNegativeNumber
    duration: NonNegativeNumber


class OpenerCapabilities(_APIModel):
    """Available local actions and path details for the requesting browser."""

    open: bool
    reveal: bool
    folders: bool
    system: OpenerSystem | None = None
    root: str | None = None
    sep: str


class OpenMediaRequest(_APIModel):
    """Open a media file or reveal it in its containing folder."""

    reveal: StrictBool


class OpenPostRequest(_APIModel):
    """Open a post folder with an empty JSON object as the request body."""
