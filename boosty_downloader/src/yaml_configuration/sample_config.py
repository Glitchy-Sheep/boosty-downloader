"""Helper functions for working with invalid values in the config."""

DEFAULT_YAML_CONFIG_VALUE = """
auth:
  # Insert your own cookie and auth header values here
  cookie: ''
  auth_header: ''
  # OAuth tokens file path (will be created automatically if OAuth is used)
  oauth_tokens_file: 'oauth_tokens.json'
downloading_settings:
  target_directory: ./boosty-downloads
"""
