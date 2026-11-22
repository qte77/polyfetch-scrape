"""``fetch(..., stream_to=Path)`` — stream a 2xx body to disk instead of memory (#261).

Real loopback server, no mocks: the streaming APIs (httpx ``send(stream=True)``,
curl_cffi ``request(stream=True)`` + ``iter_content``) are exactly the kind of
surface a lenient mock would let a wrong kwarg slip through (see the #295 note in
``test_curl_backend.py``), so every case here drives the real client against a
real socket on 127.0.0.1. No real DNS or egress.
"""

import errno
import hashlib
import http.server
import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import Result
from typer.testing import CliRunner

from polyfetch_scrape._backends import FingerprintBlock, _stream, curl_backend, httpx_backend
from polyfetch_scrape.cli import app
from polyfetch_scrape.client import fetch
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.retry import RetryPolicy
from tests.conftest import REAL_GETADDRINFO

# 3 chunks of 64 KiB: large enough that both clients yield it in more than one piece.
_PAYLOAD = bytes(range(256)) * 768
_ONE = RetryPolicy(max_attempts=1)
_TWO = RetryPolicy(max_attempts=2, backoff_initial=0.0)


class _Handler(http.server.BaseHTTPRequestHandler):
    requests: int = 0  # GETs served this test (reset by the base_url fixture)

    def do_GET(self) -> None:
        type(self).requests += 1
        if self.path == "/ok":
            self._send(200, "application/zip", _PAYLOAD)
        elif self.path == "/empty-html":
            self._send(200, "text/html", b"")
        elif self.path == "/empty-json":
            self._send(200, "application/json", b"")
        elif self.path == "/error":
            self._send(500, "text/plain", b"boom" * 4096)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/forbidden":
            self._send(403, "text/plain", b"blocked")
        elif self.path == "/not-modified":
            self.send_response(304)
            self.end_headers()
        elif self.path == "/drip":
            # 1 KiB every 0.1 s (~10 KiB/s) for ~6 s.
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(60 * 1024))
            self.end_headers()
            for _ in range(60):
                self.wfile.write(b"x" * 1024)
                self.wfile.flush()
                time.sleep(0.1)
        elif self.path == "/error-drip":
            # A 500 whose 1 KiB body arrives 64 B every 0.25 s (~4 s, 256 B/s: well above
            # curl's own < 1 byte/s low-speed abort).
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "1024")
            self.end_headers()
            for _ in range(16):
                self.wfile.write(b"e" * 64)
                self.wfile.flush()
                time.sleep(0.25)
        elif self.path == "/stall-after-data":
            # Some bytes, then silence: no further chunk ever arrives to check a deadline on.
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", "100000")
            self.end_headers()
            self.wfile.write(b"x" * 1000)
            self.wfile.flush()
            time.sleep(10)
        elif self.path == "/truncated":
            # Promise the whole payload, send a third of it, then drop the connection.
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(_PAYLOAD)))
            self.end_headers()
            self.wfile.write(_PAYLOAD[: len(_PAYLOAD) // 3])
            self.wfile.flush()
            self.close_connection = True

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class _Server(http.server.ThreadingHTTPServer):
    def handle_error(self, request: object, client_address: object) -> None:
        pass  # clients drop mid-body on purpose (truncation, deadline); not a test failure


@pytest.fixture
def base_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    # The suite stubs socket.getaddrinfo to a public address (tests/conftest.py); httpx
    # resolves even an IP literal through it, so loopback needs the real resolver back.
    monkeypatch.setattr(socket, "getaddrinfo", REAL_GETADDRINFO)
    _Handler.requests = 0
    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def _leftovers(directory: Path, target: Path) -> list[str]:
    """Every file in ``directory`` other than ``target`` — i.e. stray temp files."""
    return sorted(p.name for p in directory.iterdir() if p != target)


@pytest.mark.parametrize("tier", ["httpx", "curl_cffi"])
def test_stream_to_writes_the_body_to_disk_not_memory(
    base_url: str, tmp_path: Path, tier: str
) -> None:
    target = tmp_path / "pkg.zip"

    resp = fetch(f"{base_url}/ok", tier=tier, stream_to=target, retry=_ONE)  # type: ignore[arg-type]

    assert target.read_bytes() == _PAYLOAD
    assert resp.status == 200
    assert resp.body == b""
    assert resp.saved_to == target
    assert resp.saved_size == len(_PAYLOAD)
    assert resp.saved_sha256 == hashlib.sha256(_PAYLOAD).hexdigest()
    assert resp.backend == tier
    assert _leftovers(tmp_path, target) == []


@pytest.mark.parametrize("tier", ["httpx", "curl_cffi"])
def test_stream_to_mid_stream_failure_leaves_no_file(
    base_url: str, tmp_path: Path, tier: str
) -> None:
    target = tmp_path / "pkg.zip"

    with pytest.raises(FetchError):
        fetch(f"{base_url}/truncated", tier=tier, stream_to=target, retry=_ONE)  # type: ignore[arg-type]

    assert not target.exists()
    assert _leftovers(tmp_path, target) == []


@pytest.mark.parametrize("tier", ["httpx", "curl_cffi"])
def test_stream_to_cleans_up_between_retries(base_url: str, tmp_path: Path, tier: str) -> None:
    target = tmp_path / "pkg.zip"

    with pytest.raises(FetchError):
        fetch(f"{base_url}/truncated", tier=tier, stream_to=target, retry=_TWO)  # type: ignore[arg-type]

    assert list(tmp_path.iterdir()) == []


def test_stream_to_cleans_up_across_tier_escalation(base_url: str, tmp_path: Path) -> None:
    # httpx soft-blocks (empty HTML 2xx) → escalates to curl_cffi, which soft-blocks too.
    target = tmp_path / "page.html"

    with pytest.raises(FetchError):
        fetch(f"{base_url}/empty-html", max_tier="curl_cffi", stream_to=target, retry=_ONE)

    assert list(tmp_path.iterdir()) == []


def test_stream_to_curl_keeps_the_total_timeout_of_a_buffered_fetch(
    base_url: str, tmp_path: Path
) -> None:
    # Buffered curl_cffi caps the whole transfer at `timeout`; its stream mode only times
    # out a stalled read, so a steady ~6 s drip would run past a 2 s timeout unless the
    # loop enforces it. (curl's own low-speed abort can also fire first on a loaded host;
    # either way the fetch must end near the timeout — the deadline itself is pinned
    # deterministically by the unit test below.)
    target = tmp_path / "pkg.zip"
    started = time.monotonic()

    with pytest.raises(FetchError, match=r"(?i)timeout"):
        fetch(f"{base_url}/drip", tier="curl_cffi", stream_to=target, timeout=2.0, retry=_ONE)

    assert time.monotonic() - started < 4.0
    assert list(tmp_path.iterdir()) == []


def test_stream_to_curl_error_body_is_held_to_the_timeout_too(
    base_url: str, tmp_path: Path
) -> None:
    # The excerpt of a streamed error/retry body is read under the same deadline as a
    # 2xx body; buffered curl_cffi would end this ~4 s error drip at timeout=1.
    target = tmp_path / "pkg.zip"
    started = time.monotonic()

    with pytest.raises(FetchError):
        fetch(f"{base_url}/error-drip", tier="curl_cffi", stream_to=target, timeout=1.0, retry=_ONE)

    assert time.monotonic() - started < 2.5
    assert list(tmp_path.iterdir()) == []


def test_stream_to_curl_stall_after_data_ends_at_the_timeout(base_url: str, tmp_path: Path) -> None:
    # Without a libcurl total timeout, curl_cffi's stream mode only ends this through its
    # low-speed abort, about timeout + 6 s later (measured on curl_cffi 0.17.0).
    target = tmp_path / "pkg.zip"
    started = time.monotonic()

    with pytest.raises(FetchError):
        fetch(
            f"{base_url}/stall-after-data",
            tier="curl_cffi",
            stream_to=target,
            timeout=1.0,
            retry=_ONE,
        )

    assert time.monotonic() - started < 3.0
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("tier", ["httpx", "curl_cffi"])
def test_stream_to_failed_download_keeps_an_existing_target_intact(
    base_url: str, tmp_path: Path, tier: str
) -> None:
    target = tmp_path / "pkg.zip"
    target.write_bytes(b"previous good copy")

    with pytest.raises(FetchError):
        fetch(f"{base_url}/truncated", tier=tier, stream_to=target, retry=_ONE)  # type: ignore[arg-type]

    assert target.read_bytes() == b"previous good copy"
    assert _leftovers(tmp_path, target) == []


@pytest.mark.parametrize("tier", ["httpx", "curl_cffi"])
def test_stream_to_error_status_writes_nothing_and_keeps_a_bounded_excerpt(
    base_url: str, tmp_path: Path, tier: str
) -> None:
    target = tmp_path / "pkg.zip"

    with pytest.raises(FetchError) as excinfo:
        fetch(
            f"{base_url}/error",
            tier=tier,  # type: ignore[arg-type]
            stream_to=target,
            retry=_TWO,
        )

    assert excinfo.value.status == 500
    assert excinfo.value.body_excerpt is not None
    assert excinfo.value.body_excerpt.startswith("boom")
    assert len(excinfo.value.body_excerpt) <= 2048
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("attempt", "kwargs"),
    [(httpx_backend.attempt, {}), (curl_backend.attempt, {"browser": "chrome"})],
)
def test_stream_to_empty_html_2xx_is_still_a_soft_block(
    base_url: str, tmp_path: Path, attempt: object, kwargs: dict[str, str]
) -> None:
    target = tmp_path / "page.html"

    with pytest.raises(FingerprintBlock):
        attempt(  # type: ignore[operator]
            "GET", f"{base_url}/empty-html", None, 5.0, _ONE, stream_to=target, **kwargs
        )

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("tier", ["httpx", "curl_cffi"])
def test_stream_to_any_other_empty_body_fails_without_a_file(
    base_url: str, tmp_path: Path, tier: str
) -> None:
    target = tmp_path / "data.json"

    with pytest.raises(FetchError, match="empty"):
        fetch(f"{base_url}/empty-json", tier=tier, stream_to=target, retry=_ONE)  # type: ignore[arg-type]

    assert list(tmp_path.iterdir()) == []


def test_stream_to_unfollowed_redirect_is_returned_without_a_file(
    base_url: str, tmp_path: Path
) -> None:
    # httpx never follows redirects (#260): the 3xx comes back as-is and nothing is saved.
    target = tmp_path / "pkg.zip"

    resp = fetch(f"{base_url}/redirect", tier="httpx", stream_to=target, retry=_ONE)

    assert resp.status == 302
    assert resp.redirect_to == "/ok"
    assert resp.saved_to is None
    assert list(tmp_path.iterdir()) == []


def test_stream_to_is_rejected_on_the_patchright_tier(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="patchright"):
        fetch("https://example.com/", tier="patchright", stream_to=tmp_path / "x")


def test_stream_to_needs_an_existing_parent_directory(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="directory"):
        fetch("https://example.com/", tier="httpx", stream_to=tmp_path / "missing" / "x.zip")


@pytest.mark.parametrize("tier", ["httpx", "curl_cffi"])
def test_stream_to_works_with_a_pinned_connection(base_url: str, tmp_path: Path, tier: str) -> None:
    # RFC 2606 .invalid never resolves, so a saved payload proves the pin was used (#240).
    host = "pin-test-stream.invalid"
    port = base_url.rsplit(":", 1)[1]
    target = tmp_path / "pkg.zip"

    resp = fetch(
        f"http://{host}:{port}/ok",
        tier=tier,  # type: ignore[arg-type]
        stream_to=target,
        retry=_ONE,
        pinned_ip="127.0.0.1",
        pinned_host=host,
    )

    assert target.read_bytes() == _PAYLOAD
    assert resp.url == f"http://{host}:{port}/ok"


@pytest.mark.parametrize("tier", ["httpx", "curl_cffi"])
def test_stream_to_disk_failure_is_a_fetcherror_and_not_retried(
    base_url: str, tmp_path: Path, tier: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object) -> None:
        raise PermissionError("read-only target")

    monkeypatch.setattr("polyfetch_scrape._backends._stream.os.replace", refuse)
    target = tmp_path / "pkg.zip"

    with pytest.raises(FetchError, match="moving the download"):
        fetch(f"{base_url}/ok", tier=tier, stream_to=target, retry=RetryPolicy())  # type: ignore[arg-type]

    assert _Handler.requests == 1
    assert list(tmp_path.iterdir()) == []


def test_stream_to_saves_with_the_mode_a_plain_write_gets(base_url: str, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.write_bytes(b"x")
    target = tmp_path / "pkg.zip"

    fetch(f"{base_url}/ok", tier="httpx", stream_to=target, retry=_ONE)

    assert target.stat().st_mode == plain.stat().st_mode


def test_stream_to_rejects_a_directory_before_any_request(base_url: str, tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="directory, not a file"):
        fetch(f"{base_url}/ok", tier="httpx", stream_to=tmp_path)

    assert _Handler.requests == 0


def test_stream_to_fsyncs_the_temp_file_before_it_replaces_the_target(
    base_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        events.append("fsync")
        real_fsync(fd)

    def replace(src: Path, dst: Path) -> None:
        events.append("replace")
        real_replace(src, dst)

    monkeypatch.setattr(_stream.os, "fsync", fsync)
    monkeypatch.setattr(_stream.os, "replace", replace)

    fetch(f"{base_url}/ok", tier="httpx", stream_to=tmp_path / "pkg.zip", retry=_ONE)

    assert events == ["fsync", "replace"]


def test_stream_to_fsync_failure_is_a_fetcherror_and_leaves_no_file(
    base_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fsync(_fd: int) -> None:
        raise OSError(errno.EIO, "input/output error")

    monkeypatch.setattr(_stream.os, "fsync", fsync)
    target = tmp_path / "pkg.zip"

    with pytest.raises(FetchError, match="flushing"):
        fetch(f"{base_url}/ok", tier="httpx", stream_to=target, retry=RetryPolicy())

    assert _Handler.requests == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("tier", ["httpx", "curl_cffi"])
def test_stream_to_replaces_a_symlinked_target_and_leaves_its_referent_alone(
    base_url: str, tmp_path: Path, tier: str
) -> None:
    referent = tmp_path / "referent.bin"
    referent.write_bytes(b"untouched")
    target = tmp_path / "link.zip"
    target.symlink_to(referent)

    fetch(f"{base_url}/ok", tier=tier, stream_to=target, retry=_ONE)  # type: ignore[arg-type]

    assert not target.is_symlink()
    assert target.read_bytes() == _PAYLOAD
    assert referent.read_bytes() == b"untouched"


class _FullDisk:
    """A file whose writes fail like a full disk."""

    def __init__(self, real: object) -> None:
        self._real = real

    def write(self, _data: bytes) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


@pytest.mark.parametrize("tier", ["httpx", "curl_cffi"])
def test_stream_to_write_time_disk_error_is_a_fetcherror_and_not_retried(
    base_url: str, tmp_path: Path, tier: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = Path.open
    monkeypatch.setattr(Path, "open", lambda self, mode="r": _FullDisk(real_open(self, mode)))
    target = tmp_path / "pkg.zip"

    with pytest.raises(FetchError, match=r"writing .*No space left"):
        fetch(f"{base_url}/ok", tier=tier, stream_to=target, retry=RetryPolicy())  # type: ignore[arg-type]

    assert _Handler.requests == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("tier", ["httpx", "curl_cffi"])
def test_stream_to_create_time_disk_error_is_a_fetcherror_and_not_retried(
    base_url: str, tmp_path: Path, tier: str
) -> None:
    # A target name at the filesystem limit is creatable, but the dotted temp name beside
    # it is longer than the limit, so creating the temp file fails with ENAMETOOLONG.
    target = tmp_path / ("a" * 250)

    with pytest.raises(FetchError, match="creating a temp file"):
        fetch(f"{base_url}/ok", tier=tier, stream_to=target, retry=RetryPolicy())  # type: ignore[arg-type]

    assert _Handler.requests == 1
    assert list(tmp_path.iterdir()) == []


def _chunks_then(exc: BaseException) -> Iterator[bytes]:
    yield b"partial"
    raise exc


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), SystemExit(2)])
def test_stream_to_baseexception_mid_stream_leaves_no_temp_file(
    tmp_path: Path, exc: BaseException
) -> None:
    target = tmp_path / "pkg.zip"

    with pytest.raises(type(exc)):
        _stream.save_streamed_body(
            "GET", 200, "application/zip", _chunks_then(exc), target, "http://x/"
        )

    assert list(tmp_path.iterdir()) == []


def test_stream_to_temp_file_removal_failure_is_reported_like_a_disk_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("cannot unlink")

    monkeypatch.setattr(Path, "unlink", refuse)

    with pytest.raises(FetchError, match="removing the temp file"):
        _stream.save_streamed_body(
            "GET",
            200,
            "application/zip",
            _chunks_then(ConnectionError("dropped")),
            tmp_path / "pkg.zip",
            "http://x/",
        )


def test_stream_to_curl_unfollowed_redirect_is_returned_without_a_file(
    base_url: str, tmp_path: Path
) -> None:
    # curl_cffi follows redirects itself unless pinned (guarded fetches pin); pinned, the
    # raw 3xx comes back and nothing is saved.
    host = "pin-test-redirect.invalid"
    port = base_url.rsplit(":", 1)[1]
    target = tmp_path / "pkg.zip"

    resp = fetch(
        f"http://{host}:{port}/redirect",
        tier="curl_cffi",
        stream_to=target,
        retry=_ONE,
        pinned_ip="127.0.0.1",
        pinned_host=host,
    )

    assert resp.status == 302
    assert resp.saved_to is None
    assert resp.body == b""
    assert list(tmp_path.iterdir()) == []


def test_stream_to_escalation_reaching_patchright_fails_without_a_file(
    base_url: str, tmp_path: Path
) -> None:
    # httpx 403 -> curl_cffi 403 -> patchright, which has no body stream: FetchError, no file.
    target = tmp_path / "pkg.zip"

    with pytest.raises(FetchError, match="patchright"):
        fetch(f"{base_url}/forbidden", stream_to=target, retry=_ONE)

    assert list(tmp_path.iterdir()) == []


def test_curl_stream_deadline_uses_the_modules_own_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Patches curl_backend's own clock reference: patching time.monotonic itself would
    # also move every other caller's clock (retry loop, httpx, the test runner).
    clock = iter([10.0, 10.5, 11.5])  # before chunks 1, 2, 3
    monkeypatch.setattr(curl_backend, "_monotonic", lambda: next(clock))
    chunks = curl_backend._within_deadline(  # pyright: ignore[reportPrivateUsage]
        iter([b"a", b"b", b"c"]), deadline=11.0, timeout=1.0, url="http://x/"
    )

    assert next(chunks) == b"a"
    assert next(chunks) == b"b"
    with pytest.raises(TimeoutError, match=r"stream exceeded timeout=1\.0s"):
        next(chunks)


def test_stream_to_curl_deadline_wrapper_alone_ends_a_steady_drip(
    base_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Drop libcurl's whole-transfer timeout: the ~6 s drip at ~10 KiB/s never trips curl's
    # low-speed abort, so only the between-chunks deadline can end it at timeout=2.
    monkeypatch.setattr(curl_backend, "_with_total_timeout", lambda kwargs, _timeout: kwargs)
    target = tmp_path / "pkg.zip"
    started = time.monotonic()

    with pytest.raises(FetchError, match=r"(?i)timeout"):
        fetch(f"{base_url}/drip", tier="curl_cffi", stream_to=target, timeout=2.0, retry=_ONE)

    assert time.monotonic() - started < 4.5
    assert list(tmp_path.iterdir()) == []


def test_stream_to_curl_zero_timeout_means_no_limit_like_a_buffered_fetch(
    base_url: str, tmp_path: Path
) -> None:
    # Buffered curl_cffi maps timeout=0 to libcurl's "no timeout"; streamed must agree.
    target = tmp_path / "pkg.zip"

    resp = fetch(f"{base_url}/ok", tier="curl_cffi", stream_to=target, timeout=0, retry=_ONE)

    assert resp.saved_size == len(_PAYLOAD)
    assert target.read_bytes() == _PAYLOAD


# --- CLI: `polyfetch fetch URL --output FILE` (#303), same real loopback server ---

_CLI = CliRunner()


def _cli_fetch(url: str, *extra: str) -> Result:
    return _CLI.invoke(app, ["fetch", url, "--tier", "httpx", "--max-attempts", "1", *extra])


def test_cli_output_streams_the_body_to_the_file(base_url: str, tmp_path: Path) -> None:
    target = tmp_path / "pkg.zip"

    result = _cli_fetch(f"{base_url}/ok", "--output", str(target), "--json")

    assert result.exit_code == 0, result.output
    assert target.read_bytes() == _PAYLOAD
    payload = json.loads(result.stdout)
    assert payload["saved_to"] == str(target)
    assert payload["saved_size"] == len(_PAYLOAD)
    assert payload["saved_sha256"] == hashlib.sha256(_PAYLOAD).hexdigest()
    assert payload["bytes"] == len(_PAYLOAD)
    assert _leftovers(tmp_path, target) == []


@pytest.mark.parametrize("path", ["/error", "/truncated"])
def test_cli_output_failure_exits_nonzero_and_keeps_the_old_file(
    base_url: str, tmp_path: Path, path: str
) -> None:
    target = tmp_path / "pkg.zip"
    target.write_bytes(b"previous good copy")

    result = _cli_fetch(f"{base_url}{path}", "--output", str(target))

    assert result.exit_code == 1
    assert target.read_bytes() == b"previous good copy"
    assert _leftovers(tmp_path, target) == []


def test_cli_output_unfollowed_redirect_exits_nonzero_without_a_file(
    base_url: str, tmp_path: Path
) -> None:
    target = tmp_path / "pkg.zip"

    result = _cli_fetch(f"{base_url}/redirect", "--output", str(target))

    assert result.exit_code == 1
    assert "302" in result.stderr
    assert "/ok" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_cli_output_and_show_body_are_mutually_exclusive(base_url: str, tmp_path: Path) -> None:
    result = _cli_fetch(f"{base_url}/ok", "--output", str(tmp_path / "x"), "--show-body")

    assert result.exit_code == 2
    assert _Handler.requests == 0
    assert list(tmp_path.iterdir()) == []


def test_cli_output_not_modified_exits_nonzero_and_keeps_the_old_file(
    base_url: str, tmp_path: Path
) -> None:
    # A conditional GET's 304 saves nothing: exit 1, so a script never mistakes it for a download.
    target = tmp_path / "pkg.zip"
    target.write_bytes(b"cached copy")

    result = _cli_fetch(f"{base_url}/not-modified", "--output", str(target), "--etag", '"v1"')

    assert result.exit_code == 1
    assert "304" in result.stderr
    assert target.read_bytes() == b"cached copy"
    assert _leftovers(tmp_path, target) == []


def test_cli_output_not_saved_json_carries_the_error_type_and_reason(
    base_url: str, tmp_path: Path
) -> None:
    target = tmp_path / "pkg.zip"

    result = _cli_fetch(f"{base_url}/redirect", "--output", str(target), "--json")

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == 302
    assert payload["redirect_to"] == "/ok"
    assert payload["error_type"] == "NotSaved"
    assert payload["message"] in result.stderr
    assert "unfollowed HTTP 302 redirect to /ok" in payload["message"]


def test_cli_output_not_modified_json_carries_the_error_type_and_reason(
    base_url: str, tmp_path: Path
) -> None:
    result = _cli_fetch(
        f"{base_url}/not-modified", "--output", str(tmp_path / "x"), "--etag", '"v1"', "--json"
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "NotSaved"
    assert payload["message"] in result.stderr
    assert "304" in payload["message"]


def test_cli_output_text_summary_ends_with_the_saved_to_suffix(
    base_url: str, tmp_path: Path
) -> None:
    target = tmp_path / "pkg.zip"

    result = _cli_fetch(f"{base_url}/ok", "--output", str(target))

    assert result.exit_code == 0, result.output
    assert result.stdout.strip().endswith(
        f"{len(_PAYLOAD)} bytes  application/zip  saved to {target}"
    )


def test_cli_short_o_is_an_alias_for_output(base_url: str, tmp_path: Path) -> None:
    target = tmp_path / "pkg.zip"

    result = _cli_fetch(f"{base_url}/ok", "-o", str(target))

    assert result.exit_code == 0, result.output
    assert target.read_bytes() == _PAYLOAD


def test_cli_output_escalating_to_patchright_exits_nonzero_without_a_file(
    base_url: str, tmp_path: Path
) -> None:
    # Default tier range: httpx 403 -> curl_cffi 403 -> patchright cannot stream.
    target = tmp_path / "pkg.zip"

    result = _CLI.invoke(
        app, ["fetch", f"{base_url}/forbidden", "--max-attempts", "1", "--output", str(target)]
    )

    assert result.exit_code == 1
    assert "patchright" in result.stderr
    assert list(tmp_path.iterdir()) == []
