"""Storage-neutral library failures exposed to browsing callers."""


class LibraryReadError(RuntimeError):
    """The library cannot provide a valid readable snapshot of the requested data."""


class LibraryWriteError(RuntimeError):
    """A mark update could not persist or refresh its disposable projection."""


class LibraryMarkConflictError(RuntimeError):
    """The known post or media state does not allow the requested mark change."""
