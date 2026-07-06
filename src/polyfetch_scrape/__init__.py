import logging

from polyfetch_scrape.client import (
    AuthRequired,
    FetchError,
    GoneError,
    LegalBlock,
    RenderAction,
    RenderOptions,
    fetch,
)
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy, should_retry

# Library-logging convention: silent unless the application configures handlers.
logging.getLogger("polyfetch_scrape").addHandler(logging.NullHandler())

__all__ = [
    "AuthRequired",
    "FetchError",
    "GoneError",
    "LegalBlock",
    "RenderAction",
    "RenderOptions",
    "Response",
    "RetryPolicy",
    "fetch",
    "should_retry",
]
