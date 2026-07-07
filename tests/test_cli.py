import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from polyfetch_scrape.cli import app
from polyfetch_scrape.errors import AuthRequired, FetchError, GoneError, LegalBlock
from polyfetch_scrape.response import Response

runner = CliRunner()


def _ok(url: str = "https://example.com", status: int = 200) -> Response:
    return Response(
        url=url,
        status=status,
        headers={"content-type": "text/html"},
        body=b"<html/>",
        content_type="text/html",
        backend="httpx",
    )


def test_fetch_prints_human_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("polyfetch_scrape.cli.fetch", lambda *a, **kw: _ok())

    result = runner.invoke(app, ["fetch", "https://example.com"])

    assert result.exit_code == 0
    assert "200" in result.stdout
    assert "[httpx]" in result.stdout
    assert "https://example.com" in result.stdout


def test_fetch_json_flag_emits_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "polyfetch_scrape.cli.fetch",
        lambda *a, **kw: _ok(url="https://x.test", status=204),
    )

    result = runner.invoke(app, ["fetch", "https://x.test", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["url"] == "https://x.test"
    assert payload["status"] == 204
    assert payload["backend"] == "httpx"
    assert payload["bytes"] == len(b"<html/>")


def test_fetch_show_body_writes_raw_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Non-UTF-8 + NUL bytes: the old decode("utf-8","replace") path mangled these and
    # emitted nothing on non-UTF-8 stdout. The fix writes the raw bytes verbatim (#66).
    body = b"\xff\xfe\x00<html>caf\xc3\xa9</html>"
    resp = Response(
        url="https://x.test",
        status=200,
        headers={"content-type": "text/html"},
        body=body,
        content_type="text/html",
        backend="httpx",
    )
    monkeypatch.setattr("polyfetch_scrape.cli.fetch", lambda *a, **kw: resp)

    result = runner.invoke(app, ["fetch", "https://x.test", "--show-body"])

    assert result.exit_code == 0
    assert result.stdout_bytes == body


def test_fetch_render_flags_build_render_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake(url: str, **kwargs: object) -> Response:
        captured.update(kwargs)
        return _ok(url=url)

    monkeypatch.setattr("polyfetch_scrape.cli.fetch", fake)

    result = runner.invoke(
        app,
        [
            "fetch",
            "https://x.test",
            "--tier",
            "playwright",
            "--wait-until",
            "networkidle",
            "--wait-for-selector",
            ".q",
            "--wait-for-function",
            "window.ready",
            "--screenshot",
            "viewport",
        ],
    )

    assert result.exit_code == 0
    render = captured["render"]
    assert render.wait_until == "networkidle"  # type: ignore[attr-defined]
    assert render.wait_for_selector == ".q"  # type: ignore[attr-defined]
    assert render.wait_for_function == "window.ready"  # type: ignore[attr-defined]
    assert render.screenshot == "viewport"  # type: ignore[attr-defined]


def test_fetch_conditional_flags_reach_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake(url: str, **kwargs: object) -> Response:
        captured.update(kwargs)
        return _ok(url=url)

    monkeypatch.setattr("polyfetch_scrape.cli.fetch", fake)

    result = runner.invoke(
        app,
        [
            "fetch",
            "https://x.test",
            "--etag",
            '"abc123"',
            "--if-modified-since",
            "Wed, 21 Oct 2015 07:28:00 GMT",
        ],
    )

    assert result.exit_code == 0
    assert captured["etag"] == '"abc123"'
    assert captured["last_modified"] == "Wed, 21 Oct 2015 07:28:00 GMT"


def test_fetch_tier_range_flags_reach_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake(url: str, **kwargs: object) -> Response:
        captured.update(kwargs)
        return _ok(url=url)

    monkeypatch.setattr("polyfetch_scrape.cli.fetch", fake)

    result = runner.invoke(
        app,
        ["fetch", "https://x.test", "--min-tier", "curl_cffi", "--max-tier", "playwright"],
    )

    assert result.exit_code == 0
    assert captured["min_tier"] == "curl_cffi"
    assert captured["max_tier"] == "playwright"


def test_fetch_rejects_unknown_tier_value(monkeypatch: pytest.MonkeyPatch) -> None:
    # An invalid tier choice is rejected by typer (exit 2) before fetch() is ever called.
    called = False

    def fake(url: str, **kwargs: object) -> Response:
        nonlocal called
        called = True
        return _ok(url=url)

    monkeypatch.setattr("polyfetch_scrape.cli.fetch", fake)

    result = runner.invoke(app, ["fetch", "https://x.test", "--min-tier", "bogus"])

    assert result.exit_code == 2
    assert called is False


def test_fetch_screenshot_out_writes_png(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\nFAKE"

    def fake(url: str, **_kw: object) -> Response:
        return Response(
            url=url,
            status=200,
            headers={"content-type": "image/png"},
            body=b"x",
            content_type="image/png",
            backend="playwright",
            screenshot=png,
        )

    monkeypatch.setattr("polyfetch_scrape.cli.fetch", fake)
    out = tmp_path / "shot.png"

    result = runner.invoke(
        app,
        [
            "fetch",
            "https://x.test",
            "--tier",
            "playwright",
            "--screenshot",
            "viewport",
            "--screenshot-out",
            str(out),
        ],
    )

    assert result.exit_code == 0
    assert out.read_bytes() == png


def test_fetch_exits_1_on_fetcherror(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_kw: object) -> Response:
        raise FetchError("simulated")

    monkeypatch.setattr("polyfetch_scrape.cli.fetch", boom)

    result = runner.invoke(app, ["fetch", "https://blocked"])

    assert result.exit_code == 1
    assert "simulated" in (result.stderr or "") + result.stdout


@pytest.mark.parametrize(
    ("exc", "error_type", "status"),
    [
        (GoneError("terminal HTTP 404: u", status=404), "GoneError", 404),
        (AuthRequired("terminal HTTP 401: u", status=401), "AuthRequired", 401),
        (LegalBlock("terminal HTTP 451: u", status=451), "LegalBlock", 451),
        (FetchError("retries exhausted"), "FetchError", None),
    ],
)
def test_fetch_json_emits_structured_error(
    monkeypatch: pytest.MonkeyPatch, exc: FetchError, error_type: str, status: int | None
) -> None:
    def boom(*_a: object, **_kw: object) -> Response:
        raise exc

    monkeypatch.setattr("polyfetch_scrape.cli.fetch", boom)

    result = runner.invoke(app, ["fetch", "https://x.test", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["url"] == "https://x.test"
    assert payload["error_type"] == error_type
    assert payload["status"] == status
    assert payload["message"] == str(exc)


def test_bulk_emits_one_jsonline_per_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    urls = ["https://a.test", "https://b.test", "https://c.test"]
    listfile = tmp_path / "urls.txt"
    listfile.write_text("\n".join(urls) + "\n")

    monkeypatch.setattr("polyfetch_scrape.cli.fetch", lambda url, **_kw: _ok(url=url, status=200))

    result = runner.invoke(app, ["bulk", str(listfile)])

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 3
    payloads = [json.loads(line) for line in lines]
    assert {p["url"] for p in payloads} == set(urls)


def test_bulk_skips_comment_and_blank_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    listfile = tmp_path / "targets.txt"
    listfile.write_text(
        "# a comment\n\nhttps://a.test\n  # indented comment\nhttps://b.test\n   \n"
    )

    monkeypatch.setattr("polyfetch_scrape.cli.fetch", lambda url, **_kw: _ok(url=url, status=200))

    result = runner.invoke(app, ["bulk", str(listfile)])

    assert result.exit_code == 0
    emitted = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert {p["url"] for p in emitted} == {"https://a.test", "https://b.test"}


def test_bulk_continues_on_error_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    urls = ["https://a.test", "https://b.test", "https://c.test"]
    listfile = tmp_path / "urls.txt"
    listfile.write_text("\n".join(urls) + "\n")

    def fake(url: str, **_kw: object) -> Response:
        if url == "https://b.test":
            raise FetchError("middle url failed")
        return _ok(url=url)

    monkeypatch.setattr("polyfetch_scrape.cli.fetch", fake)

    result = runner.invoke(app, ["bulk", str(listfile)])

    assert result.exit_code == 1
    lines = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 3
    by_url = {line["url"]: line for line in lines}
    assert by_url["https://b.test"]["error_type"] == "FetchError"
    assert by_url["https://b.test"]["status"] is None
    assert "error_type" not in by_url["https://a.test"]
    assert "error_type" not in by_url["https://c.test"]


def test_bulk_workers_runs_concurrently(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    urls = [f"https://h{i}.test" for i in range(8)]
    listfile = tmp_path / "urls.txt"
    listfile.write_text("\n".join(urls) + "\n")

    def slow(url: str, **_kw: object) -> Response:
        time.sleep(0.1)
        return _ok(url=url)

    monkeypatch.setattr("polyfetch_scrape.cli.fetch", slow)

    start = time.monotonic()
    result = runner.invoke(app, ["bulk", str(listfile), "--workers", "8"])
    elapsed = time.monotonic() - start

    assert result.exit_code == 0
    assert elapsed < 0.5, f"expected concurrent under 0.5s, got {elapsed:.2f}s"


def test_version_prints_and_exits_0() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip()
