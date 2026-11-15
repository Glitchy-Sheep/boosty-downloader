"""Primary-store failures never authorize recreating the library."""


class LibraryDatabaseError(RuntimeError):
    """The primary library could not be opened or changed safely."""


class UnsupportedLibraryDatabaseError(LibraryDatabaseError):
    """The database identity or schema version is not supported."""


class UnsafeLibraryDatabasePathError(LibraryDatabaseError):
    """The database or an auxiliary path is not an ordinary unshared file."""
