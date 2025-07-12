"""Helper functions for working with invalid values in the config."""

DEFAULT_YAML_CONFIG_VALUE = """
auth:
  # Insert your own cookie and auth header values here
  cookie: ''
  auth_header: ''
  # OAuth tokens file path (will be created automatically if OAuth is used)
  oauth_tokens_file: 'oauth_tokens.json'
  # OAuth token refresh cooldown in seconds (default: 3600 = 1 hour)
  # This prevents excessive token refresh attempts for multiple inaccessible posts
  oauth_refresh_cooldown: 3600
downloading_settings:
  target_directory: ./boosty-downloads
"""
