/* Generated from the viewer API models. Regenerate with: task ui:types */

/**
 * Open a post folder with an empty JSON object as the request body.
 */
export type OpenPostRequest = Record<string, never>

/**
 * A schema generation bundle, never an HTTP response envelope.
 */
export interface ViewerAPI {
  Author: Author
  BulkMarksProgressResponse: BulkMarksProgressResponse
  BulkMarksRequest: BulkMarksRequest
  BulkMarksResult: BulkMarksResult
  ErrorBody: ErrorBody
  ErrorResponse: ErrorResponse
  FavoriteMarkRequest: FavoriteMarkRequest
  MarkResult: MarkResult
  MediaCounts: MediaCounts
  MediaFilters: MediaFilters
  MediaItem: MediaItem
  MediaPage: MediaPage
  MediaPost: MediaPost
  MediaStorage: MediaStorage
  MediaViewCounts: MediaViewCounts
  MonthCount: MonthCount
  OpenMediaRequest: OpenMediaRequest
  OpenPostRequest: OpenPostRequest
  OpenerCapabilities: OpenerCapabilities
  PositionRequest: PositionRequest
  PostDetail: PostDetail
  PostFilters: PostFilters
  PostList: PostList
  PostRow: PostRow
  SearchMatch: SearchMatch
  SearchRun: SearchRun
  SeenMarkRequest: SeenMarkRequest
  TagCount: TagCount
}
/**
 * An author's display information and complete local library totals.
 */
export interface Author {
  avatar_url: string | null
  cover_url: string | null
  description: string
  favorites: number
  locked: number
  name: string
  posts: number
  storage: MediaStorage
  title: string
  unseen: number
}
/**
 * Downloaded bytes, including retained copies removed from a post.
 */
export interface MediaStorage {
  audio: number
  files: number
  images: number
  videos: number
}
/**
 * Progress of the active bulk; the POST response reports its final outcome.
 */
export interface BulkMarksProgressResponse {
  active: boolean
  changed: number
  completed: number
  total: number | null
}
/**
 * Apply a seen value to all posts selected by normalized filters.
 */
export interface BulkMarksRequest {
  filters: PostFilters
  seen: boolean
}
/**
 * Normalized filters, also used to choose posts for bulk marks.
 */
export interface PostFilters {
  fav: boolean
  incomplete: boolean
  kind: ('images' | 'videos' | 'files' | 'audio') | null
  locked: boolean
  order: 'newest' | 'oldest'
  q: string
  tag: string | null
  unseen: boolean
}
/**
 * Number of posts whose seen mark changed.
 */
export interface BulkMarksResult {
  count: number
}
/**
 * A stable machine code and a user-facing explanation.
 */
export interface ErrorBody {
  code: string
  message: string
}
/**
 * The JSON envelope for an unsuccessful viewer request.
 */
export interface ErrorResponse {
  error: ErrorBody
}
/**
 * Change only the favorite mark on one post.
 */
export interface FavoriteMarkRequest {
  favorite: boolean
}
/**
 * The refreshed post and author after one mark changes.
 */
export interface MarkResult {
  author: Author
  post: PostRow
}
/**
 * A compact post listing without its full body or media inventory.
 */
export interface PostRow {
  access: 'open' | 'locked'
  counts: MediaCounts
  /**
   * Author-relative cover path.
   */
  cover_path: string | null
  created_at: string
  favorite: boolean
  id: string
  match: SearchMatch | null
  missing_media: number
  seen: boolean
  tier: string | null
  title: string
  updated: boolean
}
/**
 * Counts of current pieces, combining both video sources.
 */
export interface MediaCounts {
  audio: number
  files: number
  images: number
  videos: number
}
/**
 * Search highlights; a null body means only the title matched.
 */
export interface SearchMatch {
  text: SearchRun[] | null
  title: SearchRun[]
}
/**
 * A plain-text fragment and whether it matched the search.
 */
export interface SearchRun {
  matched: boolean
  text: string
}
/**
 * Normalized filters for an author's media screen.
 */
export interface MediaFilters {
  fav: boolean
  order: 'newest' | 'oldest'
  unseen: boolean
  view: 'all' | 'images' | 'videos' | 'audio' | 'files'
}
/**
 * A downloaded current or retained media file, without repeated post data.
 */
export interface MediaItem {
  artist: string | null
  created_at: string
  duration_s: number | null
  file_type:
    | 'pdf'
    | 'document'
    | 'book'
    | 'sheet'
    | 'slides'
    | 'image'
    | 'audio'
    | 'video'
    | 'archive'
    | 'model'
    | 'code'
    | 'font'
    | 'program'
    | 'script'
    | 'other'
  filename: string | null
  finished: boolean
  height: number | null
  /**
   * Opaque identity containing the post and media piece.
   */
  id: string
  kind: 'images' | 'videos' | 'files' | 'audio'
  /**
   * Author-relative file path.
   */
  path: string
  position_s: number | null
  post_id: string
  removed: boolean
  /**
   * Downloaded file size in bytes.
   */
  size: number
  /**
   * Author-relative thumbnail path.
   */
  thumb_path: string | null
  title: string | null
  width: number | null
}
/**
 * Media with shared post data, category totals and missing-file count.
 */
export interface MediaPage {
  counts: MediaViewCounts
  items: MediaItem[]
  missing: number
  posts: {
    [k: string]: MediaPost
  }
}
/**
 * Downloaded media totals for every media-screen category.
 */
export interface MediaViewCounts {
  all: number
  audio: number
  files: number
  images: number
  videos: number
}
/**
 * Display data shared by all media belonging to one post.
 */
export interface MediaPost {
  /**
   * Author-relative cover path.
   */
  cover_path: string | null
  favorite: boolean
  seen: boolean
  title: string
}
/**
 * Number of filtered posts in one UTC calendar month.
 */
export interface MonthCount {
  count: number
  month: string
}
/**
 * Open a media file or reveal it in its containing folder.
 */
export interface OpenMediaRequest {
  reveal: boolean
}
/**
 * Available local actions and path details for the requesting browser.
 */
export interface OpenerCapabilities {
  folders: boolean
  open: boolean
  reveal: boolean
  root: string | null
  sep: string
  system: ('macos' | 'windows' | 'linux' | 'android') | null
}
/**
 * Playback position and duration in finite, nonnegative seconds.
 */
export interface PositionRequest {
  duration: number
  seconds: number
}
/**
 * A post's retained body and files, independent of current access.
 */
export interface PostDetail {
  access: 'open' | 'locked'
  body_html: string
  boosty_url: string
  counts: MediaCounts
  /**
   * Author-relative cover path.
   */
  cover_path: string | null
  created_at: string
  favorite: boolean
  has_folder: boolean
  id: string
  match: SearchMatch | null
  media: MediaItem[]
  missing_media: number
  post_price_rub: number | null
  seen: boolean
  tags: string[]
  tier: string | null
  tier_price_rub: number | null
  title: string
  updated: boolean
}
/**
 * Rows, month counts and a total for the same filtered result.
 */
export interface PostList {
  months: MonthCount[]
  rows: PostRow[]
  total: number
}
/**
 * Change only the seen mark on one post.
 */
export interface SeenMarkRequest {
  seen: boolean
}
/**
 * Number of distinct posts carrying an exact stored tag.
 */
export interface TagCount {
  count: number
  tag: string
}
