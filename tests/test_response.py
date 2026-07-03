from dataclasses import FrozenInstanceError

import pytest

from polyfetch_scrape.response import Response


def test_response_holds_fields() -> None:
    # Arrange
    headers = {"content-type": "text/html"}

    # Act
    resp = Response(
        url="https://example.com",
        status=200,
        headers=headers,
        body=b"<html/>",
        content_type="text/html",
        backend="httpx",
    )

    # Assert
    assert resp.url == "https://example.com"
    assert resp.status == 200
    assert resp.headers == headers
    assert resp.body == b"<html/>"
    assert resp.content_type == "text/html"
    assert resp.backend == "httpx"
    assert resp.permanent_redirect_to is None


def test_response_surfaces_permanent_redirect() -> None:
    resp = Response(
        url="https://example.com/old",
        status=301,
        headers={"location": "https://example.com/new"},
        body=b"",
        content_type=None,
        backend="httpx",
        permanent_redirect_to="https://example.com/new",
    )

    assert resp.permanent_redirect_to == "https://example.com/new"


def test_response_is_frozen() -> None:
    # Arrange
    resp = Response(
        url="https://example.com",
        status=200,
        headers={},
        body=b"",
        content_type=None,
        backend="httpx",
    )

    # Act / Assert
    with pytest.raises(FrozenInstanceError):
        resp.status = 500  # type: ignore[misc]
