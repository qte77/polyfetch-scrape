import pytest

from polyfetch_scrape._backends import bounded_diagnostics, raise_for_terminal_status
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


def test_fetcherror_diagnostics_default_to_none() -> None:
    exc = FetchError("plain failure")
    assert exc.status is None
    assert exc.headers is None
    assert exc.body_excerpt is None


def test_fetcherror_carries_bounded_diagnostics_when_provided() -> None:
    exc = FetchError(
        "blocked",
        status=403,
        headers={"content-type": "text/html"},
        body_excerpt="<html>challenge</html>",
    )
    assert exc.status == 403
    assert exc.headers == {"content-type": "text/html"}
    assert exc.body_excerpt == "<html>challenge</html>"


def test_bounded_diagnostics_redacts_set_cookie_case_insensitively() -> None:
    headers, _ = bounded_diagnostics(
        {"Content-Type": "text/html", "Set-Cookie": "sid=abc123; HttpOnly"}, b"<html></html>"
    )
    assert headers == {"Content-Type": "text/html"}


def test_bounded_diagnostics_truncates_ascii_body_to_2kb() -> None:
    body = ("x" * 3000).encode("ascii")

    _, excerpt = bounded_diagnostics({}, body)

    assert excerpt is not None
    assert len(excerpt) == 2048
    assert excerpt == "x" * 2048


def test_bounded_diagnostics_decodes_invalid_utf8_lossily_without_raising() -> None:
    body = b"\xff\xfeinvalid-utf8-then-text"

    _, excerpt = bounded_diagnostics({}, body)

    assert excerpt is not None
    assert "invalid-utf8-then-text" in excerpt


def test_bounded_diagnostics_none_headers_and_empty_body_stay_none() -> None:
    headers, excerpt = bounded_diagnostics(None, b"")
    assert headers is None
    assert excerpt is None


def test_bounded_diagnostics_preserves_empty_headers_dict() -> None:
    headers, _ = bounded_diagnostics({}, None)
    assert headers == {}
