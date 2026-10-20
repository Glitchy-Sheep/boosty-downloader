"""Errors in saved post content or identity, distinct from filesystem failures."""


class InvalidPostRecordError(ValueError):
    """A saved record or supplied domain value violates the post format."""


class UnsupportedPostSchemaError(InvalidPostRecordError):
    """The record uses a schema version this reader does not support."""


class AmbiguousPostFolderError(ValueError):
    """More than one candidate folder matches a post lookup."""
