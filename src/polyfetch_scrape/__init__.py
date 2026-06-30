import logging

from polyfetch_scrape.client import FetchError, fetch
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy, should_retry

# Library-logging convention: silent unless the application configures handlers.
logging.getLogger("polyfetch_scrape").addHandler(logging.NullHandler())

__all__ = ["FetchError", "Response", "RetryPolicy", "fetch", "should_retry"]
