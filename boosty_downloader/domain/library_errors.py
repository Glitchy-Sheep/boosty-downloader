"""Storage-neutral library failures exposed to browsing callers."""


class LibraryReadError(RuntimeError):
    """The library cannot provide a valid readable snapshot of the requested data."""
