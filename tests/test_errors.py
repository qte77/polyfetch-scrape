import pytest

from polyfetch_scrape._backends import (
    bounded_diagnostics,
    is_suspected_soft_block,
    raise_for_terminal_status,
)
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


@pytest.mark.parametrize(
    ("method", "status", "body", "content_type"),
    [
        ("GET", 200, b"", None),
        ("GET", 200, b"", "text/html"),
        ("GET", 200, b"", "text/html; charset=utf-8"),
        ("GET", 200, b"", "TEXT/HTML"),
        ("get", 200, b"", None),  # method matched case-insensitively
        ("GET", 299, b"", None),  # top of the 2xx range
    ],
)
def test_is_suspected_soft_block_matches(
    method: str, status: int, body: bytes, content_type: str | None
) -> None:
    assert is_suspected_soft_block(method, status, body, content_type) is True


@pytest.mark.parametrize(
    ("method", "status", "body", "content_type"),
    [
        ("HEAD", 200, b"", None),  # not GET
        ("POST", 200, b"", None),  # not GET
        ("GET", 204, b"", None),  # legitimately empty — exempt
        ("GET", 304, b"", None),  # not 2xx
        ("GET", 301, b"", "text/html"),  # not 2xx
        ("GET", 200, b"non-empty", None),  # body present
        ("GET", 200, b"", "application/json"),  # non-HTML content type
        ("GET", 200, b"", "text/plain"),  # non-HTML content type
    ],
)
def test_is_suspected_soft_block_does_not_match(
    method: str, status: int, body: bytes, content_type: str | None
) -> None:
    assert is_suspected_soft_block(method, status, body, content_type) is False
