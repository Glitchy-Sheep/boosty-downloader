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
