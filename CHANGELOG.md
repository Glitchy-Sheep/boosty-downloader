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
