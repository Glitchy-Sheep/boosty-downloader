1.3.0

- **Enhanced HTML Reporter**: Complete rewrite of HTML generation with modern semantic HTML5 structure
- **Post Metadata Support**: Added comprehensive post metadata (title, dates, author, original URL) in HTML headers
- **Content Type Attributes**: Added data-content-type attributes for improved parsing (text, image, link, file, video)
- **Files and Videos in HTML**: Files and videos are now displayed in generated HTML with local links when available
- **Clickable Images**: Images can now be opened in new tabs by clicking on them
- **Structured Data**: Added JSON-LD structured data for better machine parsing and SEO
- **Modern CSS Design**: Responsive design with dark/light theme support and CSS custom properties
- **Improved URL Generation**: Fixed post URLs to include author username (boosty.to/author/posts/id format)
- **Empty Paragraph Filtering**: Removed empty paragraphs that match Boosty frontend behavior
- **Enhanced Accessibility**: Added proper alt text, loading attributes, and semantic markup
- **Content Order Preservation**: Maintains original post content order with proper spacing
- **File Size Formatting**: Human-readable file size display with proper units
- **Video Duration Display**: Shows video duration and type information when available

1.2.2

- **OAuth Token Parsing Fix**: Fixed critical issue with OAuth token parsing when copying from browser console
- **New Token Format Support**: Added support for pipe-separated string format (access_token|refresh_token|expires_at|device_id) to eliminate JSON parsing errors
- **Enhanced Error Handling**: Improved error messages and debug logging for OAuth token setup
- **Token Validation**: Added comprehensive validation for both legacy JSON format and new pipe-separated format
- **Authentication Stability**: Resolved issues with escaped JSON strings and invisible characters in OAuth tokens

1.2.1

- **Critical Bug Fix**: Fixed `target_directory` configuration parameter being ignored in main.py
- **Configuration Support**: Now properly respects both relative and absolute paths in `target_directory` setting
- **Testing**: Added comprehensive tests for `target_directory` functionality
- **Directory Creation**: Ensures target directories are created automatically when they don't exist

1.2.0

- **OAuth Authentication**: Added OAuth token-based authentication with automatic token refresh
- **Enhanced Security**: OAuth tokens are automatically refreshed when expired, reducing authentication failures
- **Browser Token Extraction**: Added JavaScript utility to extract OAuth tokens from browser cookies 
- **Dual Authentication**: Support for both OAuth (recommended) and legacy cookie/header authentication
- **OAuth Management**: New commands for OAuth setup (`oauth-setup`) and token status checking
- **Configuration Updates**: Updated config validation to support OAuth tokens file
- **Improved Documentation**: Updated README with OAuth setup instructions

1.1.0

- **Improved Cache System**: Major refactoring of the post caching architecture for better reliability
- **Fixed Cache Validation**: Cache now properly uses unique post IDs instead of titles as primary keys
- **Better Title Handling**: Automatic folder renaming when post titles change on the server
- **Enhanced Error Handling**: Added comprehensive error handling for post download failures
- **Separated Responsibilities**: Split cache checking and folder renaming into distinct, testable methods
- **Comprehensive Testing**: Added 9 new test cases covering all cache scenarios including edge cases
- **Performance Improvements**: Reduced redundant downloads through more accurate cache validation

1.0.2

- **BREAKING CHANGE**: Improved cache architecture to separate clean post titles from folder names with dates
- Cache now stores clean post titles without dates, preventing data duplication
- Fixed cache validation logic to properly compare folder names with formatted date + title

1.0.1

- Fixed import path in ok_video_ranking_test.py (moved from ok_video_ranking to utils/ok_video_ranking)
- Added __main__.py for running package via python -m boosty_downloader
- Fixed code style issues with ruff (Union -> |, import organization)
- Updated .gitignore to include macOS system files
- All tests now pass successfully

1.0.0

- First stable release
- Main downloader functions such as video/post/external_video/files
- Added CLI interface with typer (with customizable options)
