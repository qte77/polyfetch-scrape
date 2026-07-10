import logging

from polyfetch_scrape.client import (
    AuthRequired,
    FetchError,
    GoneError,
    LegalBlock,
    RenderAction,
    RenderOptions,
    Screenshot,
    fetch,
)
from polyfetch_scrape.render_session import render_session
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy, should_retry
from polyfetch_scrape.throttle import Throttle

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
    "Screenshot",
    "Throttle",
    "fetch",
    "render_session",
    "should_retry",
]
