import pytest

from polyfetch_scrape._backends import raise_for_terminal_status
from polyfetch_scrape.errors import AuthRequired, FetchError, GoneError, LegalBlock


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [
        (401, AuthRequired),
        (407, AuthRequired),
        (404, GoneError),
        (410, GoneError),
        (451, LegalBlock),
    ],
)
def test_raise_for_terminal_status_raises_mapped_type(
    status: int, exc_type: type[FetchError]
) -> None:
    with pytest.raises(exc_type):
        raise_for_terminal_status(status, "https://example.com")


@pytest.mark.parametrize("status", [200, 204, 301, 304, 403, 429, 500, 503])
def test_raise_for_terminal_status_passes_non_terminal(status: int) -> None:
    # Non-terminal statuses are handled elsewhere (retry / fingerprint / return) — no raise here.
    raise_for_terminal_status(status, "https://example.com")


@pytest.mark.parametrize("exc_type", [AuthRequired, GoneError, LegalBlock])
def test_terminal_errors_are_fetcherror_subclasses(exc_type: type[FetchError]) -> None:
    assert issubclass(exc_type, FetchError)
