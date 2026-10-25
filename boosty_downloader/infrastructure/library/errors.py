"""Errors in saved library records or identity, distinct from filesystem failures."""


class InvalidPostRecordError(ValueError):
    """A saved record or supplied domain value violates the post format."""


class UnsupportedPostSchemaError(InvalidPostRecordError):
    """The record uses a schema version this reader does not support."""


class AmbiguousPostFolderError(ValueError):
    """More than one candidate folder matches a post lookup."""


class InvalidAuthorRecordError(ValueError):
    """Author details or locked-post observations violate their JSON format."""


class UnsupportedAuthorSchemaError(InvalidAuthorRecordError):
    """An author service record uses an unsupported schema version."""
