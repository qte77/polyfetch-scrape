class FetchError(Exception):
    """Raised when a fetch fails after exhausting retries on every backend."""
