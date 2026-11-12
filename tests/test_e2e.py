"""End-to-end tests against real network endpoints.

Skipped by default (see `addopts = "-m 'not e2e'"` in pyproject.toml).
Run via `make test_e2e` or `uv run pytest -m e2e`.
"""

import http.server
import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from urllib.parse import urlparse

import pytest

from polyfetch_scrape import (
    FetchError,
    GoneError,
    RenderOptions,
    RetryPolicy,
    Screenshot,
    fetch,
    render_session,
)
from polyfetch_scrape.utils.sitemap import fetch_sitemap_urls

pytestmark = pytest.mark.e2e

_PNG_MAGIC = b"\x89PNG"


# --- Layer A: httpbin.org (deterministic, behavior-controlled) ---


def test_httpbin_get_returns_200_json() -> None:
    # Act
    resp = fetch("https://httpbin.org/get")

    # Assert
    assert resp.status == 200
    assert resp.content_type is not None
    assert resp.content_type.startswith("application/json")
    assert b'"url"' in resp.body


def test_httpbin_503_retries_then_raises() -> None:
    # Arrange
    policy = RetryPolicy(max_attempts=2, backoff_initial=0.05, backoff_factor=1.0)

    # Act / Assert
    with pytest.raises(FetchError):
        fetch("https://httpbin.org/status/503", retry=policy)


def test_httpbin_404_raises_goneerror() -> None:
    # Act / Assert: 404 is terminal — raises GoneError, not retried
    with pytest.raises(GoneError):
        fetch("https://httpbin.org/status/404")


# --- Layer B: real-world targets the roadmap cares about ---


def test_arxiv_abstract_page_succeeds_on_plain_httpx() -> None:
    """arXiv has no anti-bot — confirms stage 0.1.0 covers it."""
    resp = fetch("https://arxiv.org/abs/2301.00001")
    assert resp.status == 200
    assert resp.content_type is not None
    assert "html" in resp.content_type.lower()


def test_curl_backend_executes_against_real_target() -> None:
    """Stage 0.2.0: direct-call proof that the curl_cffi tier executes correctly.

    No public target reliably distinguishes 'needs curl_cffi' from 'httpx works'
    over time — TLS-fingerprint blocking targets decay as sites' anti-bot posture
    changes (see AGENT_LEARNINGS.md "Re-verify time-sensitive empirical data").
    The auto-fallback trigger itself is covered by the mocked unit tests, so here
    we drive curl_backend.attempt() directly to verify the tier connects with
    chrome impersonation and returns a well-formed Response.
    """
    from polyfetch_scrape._backends import curl_backend

    resp = curl_backend.attempt(
        "GET",
        "https://example.com",
        None,
        30.0,
        RetryPolicy(max_attempts=2),
        browser="chrome",
    )
    assert resp.status == 200
    assert resp.backend == "curl_cffi"


def test_patchright_backend_executes_against_real_target() -> None:
    """Stage 0.3.0: direct-call proof that the patchright tier executes correctly.

    No public target cleanly distinguishes 'needs the patchright tier' from
    'curl_cffi works' in headless CI (headed Chrome would be needed for hardened
    Cloudflare per Patchright's own README — see docs/scraping-landscape.md).
    So we drive patchright_backend.attempt() directly to verify the tier
    connects, runs JS, and returns a well-formed Response.
    """
    from polyfetch_scrape._backends import patchright_backend

    resp = patchright_backend.attempt(
        method="GET",
        url="https://httpbin.org/html",
        headers=None,
        timeout=30.0,
        policy=RetryPolicy(max_attempts=1),
    )
    assert resp.status == 200
    assert resp.backend == "patchright"
    assert b"<html" in resp.body.lower() or b"<body" in resp.body.lower()


@pytest.mark.xfail(
    reason=(
        "g2.com is Cloudflare Enterprise; passing requires headed real-Chrome "
        "(Patchright README → Best Practice), incompatible with headless CI. "
        "Out of scope for OSS-only toolkit; future fix is commercial bypass or "
        "headed-browser infra."
    ),
    strict=False,
    raises=(FetchError, AssertionError),
)
def test_g2_remains_blocked_in_headless_ci() -> None:
    """Documents the practical ceiling: even Patchright can't beat the hardest
    Cloudflare tier without headed real-Chrome, which CI doesn't provide."""
    resp = fetch("https://www.g2.com/", retry=RetryPolicy(max_attempts=1))
    assert resp.status == 200


# --- Layer C: feature-coverage targets (ToS-safe sandboxes; the weekly probe
# fails loudly if a passing target regresses — e.g. curl_cffi/patchright drift). ---


def test_render_session_drives_js_spa() -> None:
    """render_session (#117) drives an interactive JS SPA and captures a shot."""
    with render_session("https://quotes.toscrape.com/js/", wait_until="networkidle") as s:
        s.wait_for_selector(".quote")
        shot = s.shot("home")
        count = s.page.locator(".quote").count()
    assert count >= 1
    assert shot.startswith(_PNG_MAGIC)
    assert isinstance(s.console_errors, list)


def test_named_screenshots_capture_multiple() -> None:
    """RenderOptions.screenshots (#119) captures named PNGs in one render."""
    resp = fetch(
        "https://quotes.toscrape.com/js/",
        tier="patchright",
        render=RenderOptions(
            wait_until="networkidle",
            screenshots=(Screenshot("viewport", "viewport"), Screenshot("footer", ".footer")),
        ),
    )
    assert set(resp.screenshots) == {"viewport", "footer"}
    assert resp.screenshots["viewport"].startswith(_PNG_MAGIC)
    assert resp.screenshots["footer"].startswith(_PNG_MAGIC)


def test_patchright_full_page_screenshot_captures_nonzero_png() -> None:
    """full_page screenshots (#132) write a real image under patchright >= 1.61.2
    (older builds wrote 0 bytes on tall pages — this guards that regression)."""
    resp = fetch(
        "https://quotes.toscrape.com/js/",
        tier="patchright",
        render=RenderOptions(wait_until="networkidle", screenshot="full_page"),
    )
    assert resp.status == 200
    assert resp.screenshot is not None
    assert resp.screenshot.startswith(_PNG_MAGIC)
    assert len(resp.screenshot) > 1000  # a real page render, not a 0-byte stub


def test_patchright_emulation_and_video_record_real_webm(tmp_path) -> None:
    """Emulation (device/color_scheme) + video recording (#162) produce a real .webm.

    Guards the new context-time RenderOptions end-to-end against a real browser:
    the recording is finalized on context close and its path surfaces on Response.
    """
    resp = fetch(
        "https://quotes.toscrape.com/js/",
        tier="patchright",
        render=RenderOptions(
            wait_until="networkidle",
            device="iPhone 13",
            color_scheme="dark",
            record_video_dir=str(tmp_path),
        ),
    )
    assert resp.status == 200
    assert resp.backend == "patchright"
    assert resp.video_path is not None
    assert resp.video_path.suffix == ".webm"
    assert resp.video_path.exists()
    assert resp.video_path.stat().st_size > 0


def test_patchright_har_record_produces_valid_har(tmp_path) -> None:
    """HAR recording (#229) produces a valid HAR 1.2 file with the document request.

    Guards the HAR context_kwargs wiring end-to-end against a real browser: Patchright
    finalizes the file on context.close() -- same lifecycle timing as the video (#199).
    """
    har_path = tmp_path / "session.har"
    resp = fetch(
        "https://example.com",
        tier="patchright",
        render=RenderOptions(record_har_path=str(har_path)),
    )
    assert resp.status == 200
    assert resp.har_path == har_path
    assert resp.har_path.exists()

    har = json.loads(resp.har_path.read_text())
    assert har["log"]["version"] == "1.2"
    urls = [e["request"]["url"] for e in har["log"]["entries"]]
    # Exact host match, not a substring/prefix check (CodeQL: incomplete URL sanitization
    # flags "https://example.com" as a prefix that "https://example.com.evil.com" would
    # also satisfy) -- see AGENT_LEARNINGS.md "CodeQL url-substring gate".
    assert any(urlparse(u).netloc == "example.com" for u in urls)


def test_render_session_video_record_real_webm(tmp_path) -> None:
    """render_session video recording (#199) produces a real, finalized .webm.

    Guards the video-path-read-ordering fix end-to-end against a real browser: the path
    must resolve after the with-block exits, once the driver has torn down.
    """
    with render_session("https://example.com", record_video_dir=str(tmp_path)) as s:
        pass
    assert s.video_path is not None
    assert s.video_path.suffix == ".webm"
    assert s.video_path.exists()
    assert s.video_path.stat().st_size > 0


def test_patchright_headed_launch_against_real_target() -> None:
    """Headed launch (#190): the hardcoded `headless=True` ceiling is gone.

    Needs a real X display. CI runs the headed leg under `xvfb-run -a` (the issue's own CI
    note) so it stays unattended; locally, with no `DISPLAY` set, this skips cleanly instead
    of failing on Patchright's "Missing X server or $DISPLAY" — run it under `xvfb-run -a`
    (e.g. `xvfb-run -a uv run pytest -m e2e -k headed --no-cov`) to actually exercise it.
    """
    if not os.environ.get("DISPLAY"):
        pytest.skip("no DISPLAY available — run under `xvfb-run -a` to exercise headed launch")

    from polyfetch_scrape._backends import patchright_backend

    resp = patchright_backend.attempt(
        method="GET",
        url="https://example.com",
        headers=None,
        timeout=30.0,
        policy=RetryPolicy(max_attempts=1),
        render=RenderOptions(headless=False),
    )
    assert resp.status == 200
    assert resp.backend == "patchright"


def test_fetch_sitemap_urls_against_real_sitemap() -> None:
    """fetch_sitemap_urls (#33) resolves a real /sitemap.xml."""
    urls = fetch_sitemap_urls("https://www.sitemaps.org", max_urls=5)
    assert len(urls) >= 1
    assert all(u.startswith("http") for u in urls)


# --- Layer D: harder anti-bot ceilings (ToS-safe challenge sandboxes that 403
# every tier incl. headless Chromium; xfail like g2.com). A weekly xpass here is
# the signal that headless capability improved — see docs/scraping-landscape.md. ---


@pytest.mark.xfail(
    reason="scrapingcourse.com anti-bot challenge 403s all tiers incl. headless (#59 ceiling).",
    strict=False,
    raises=(FetchError, AssertionError),
)
def test_scrapingcourse_antibot_challenge_is_ceiling() -> None:
    resp = fetch(
        "https://www.scrapingcourse.com/antibot-challenge", retry=RetryPolicy(max_attempts=1)
    )
    assert resp.status == 200


@pytest.mark.xfail(
    reason="scrapingcourse.com Cloudflare challenge 403s all tiers incl. headless (#59 ceiling).",
    strict=False,
    raises=(FetchError, AssertionError),
)
def test_scrapingcourse_cloudflare_challenge_is_ceiling() -> None:
    resp = fetch(
        "https://www.scrapingcourse.com/cloudflare-challenge", retry=RetryPolicy(max_attempts=1)
    )
    assert resp.status == 200


# --- Layer E: authenticated sessions (#200) — a LOCAL fixture, not a third-party site:
# sets a cookie, then echoes back the cookies/headers a later request actually carried. ---


class _SessionFixtureHandler(http.server.BaseHTTPRequestHandler):
    """Local-only fixture for the #200 save→resume round trip: ``/set-cookie`` sets a
    cookie; ``/echo`` reports the ``Cookie`` header and any custom ``X-*`` headers it
    received, as plain visible text (not JSON) so a rendered ``page.content()`` needs no
    JSON-viewer interpretation to assert against."""

    def do_GET(self) -> None:
        if self.path == "/set-cookie":
            self._respond(
                "<html><body>cookie set</body></html>", set_cookie="session=abc123; Path=/"
            )
            return
        cookie_header = self.headers.get("Cookie", "(none)")
        extra = ";".join(f"{k}={v}" for k, v in self.headers.items() if k.lower().startswith("x-"))
        body = f"<html><body>cookie:{cookie_header}|headers:{extra}</body></html>"
        self._respond(body)

    def _respond(self, body: str, set_cookie: str | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        if set_cookie is not None:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args: object) -> None:  # silence stdout noise during the run
        pass


@pytest.fixture
def local_fixture_server() -> Iterator[str]:
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SessionFixtureHandler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            # shutdown() alone stops serve_forever() but leaves the listening socket open
            # (HTTPServer.__exit__ / server_close() closes it) -- an unclosed socket raises
            # a ResourceWarning that pytest's unraisableexception plugin turns into a hard
            # teardown error, even though the test itself passed.
            server.shutdown()
            thread.join()


def test_render_session_storage_state_save_resume_round_trip(
    tmp_path, local_fixture_server
) -> None:
    """#200: save a session's storage_state, then resume it — no re-login required."""
    state_path = tmp_path / "state.json"
    with render_session(f"{local_fixture_server}/set-cookie") as s:
        s.save_storage_state(state_path)
    assert state_path.exists()

    with render_session(f"{local_fixture_server}/echo", storage_state=str(state_path)) as s2:
        content = s2.page.content()
    assert "cookie:session=abc123" in content


def test_render_session_cookies_seed_a_direct_session(local_fixture_server) -> None:
    """RenderOptions.cookies (#200): a targeted cookie, no full storage_state round trip."""
    with render_session(
        f"{local_fixture_server}/echo",
        cookies=({"name": "session", "value": "direct456", "url": local_fixture_server},),
    ) as s:
        content = s.page.content()
    assert "cookie:session=direct456" in content


def test_fetch_storage_state_save_resume_round_trip(tmp_path, local_fixture_server) -> None:
    """#200: the one-shot fetch(render=RenderOptions(storage_state=...)) entry point also
    resumes a saved session -- render_session() covers the save side above; this covers the
    OTHER consumer of a saved storage_state (fetch's single-shot render path)."""
    state_path = tmp_path / "state.json"
    with render_session(f"{local_fixture_server}/set-cookie") as s:
        s.save_storage_state(state_path)
    assert state_path.exists()

    resp = fetch(
        f"{local_fixture_server}/echo",
        tier="patchright",
        render=RenderOptions(storage_state=str(state_path)),
    )
    assert "cookie:session=abc123" in resp.body.decode()


def test_render_session_storage_state_and_cookies_compose(tmp_path, local_fixture_server) -> None:
    """#200: a storage_state base PLUS an explicit extra cookie -- both reach the server.
    new_context(storage_state=...) seeds the context first; apply_cookies()'s add_cookies()
    call runs after, before the first navigation -- a different-name cookie is additive,
    not a replacement (Playwright's add_cookies upserts by name/domain/path)."""
    state_path = tmp_path / "state.json"
    with render_session(f"{local_fixture_server}/set-cookie") as s:
        s.save_storage_state(state_path)

    with render_session(
        f"{local_fixture_server}/echo",
        storage_state=str(state_path),
        cookies=({"name": "extra", "value": "xyz789", "url": local_fixture_server},),
    ) as s2:
        content = s2.page.content()

    assert "session=abc123" in content  # from storage_state
    assert "extra=xyz789" in content  # from cookies=, additive alongside it


def test_fetch_extra_http_headers_merge_with_fetch_headers(local_fixture_server) -> None:
    """#200: RenderOptions.extra_http_headers merges with fetch(headers=...) -- BOTH reach
    the wire, not just the fetch-level one (the clobbering bug this PR fixes)."""
    resp = fetch(
        f"{local_fixture_server}/echo",
        tier="patchright",
        headers={"X-Fetch-Only": "from-fetch"},
        render=RenderOptions(extra_http_headers={"X-Render-Only": "from-render-options"}),
    )
    text = resp.body.decode()
    assert "X-Fetch-Only=from-fetch" in text
    assert "X-Render-Only=from-render-options" in text


# --- Layer F: opt-in full network capture (#182) -- CDP Network-domain log + SSE, against
# a LOCAL fixture (not a third-party site): ok / 404 / connection-refused / an SSE stream. ---


def _find_closed_port() -> int:
    """A port nothing is listening on, for a deterministic connection-refused target."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # closed immediately -- nothing listens here now
    return port


class _NetworkCaptureFixtureHandler(http.server.BaseHTTPRequestHandler):
    """Local-only fixture for #182. ``/driver`` triggers one ok request (itself), one 404,
    one connection-refused request, and a 3-message SSE stream that the PAGE's own script
    closes once satisfied (no EventSource auto-reconnect noise, so the capture is
    deterministic). ``/stealth-check`` is a separate, minimal page for the
    navigator.webdriver comparison."""

    closed_port = 0

    def do_GET(self) -> None:
        if self.path == "/ok":
            self._html(200, "<html><body>ok</body></html>")
        elif self.path == "/missing":
            self._html(404, "<html><body>not found</body></html>")
        elif self.path == "/sse":
            self._sse()
        elif self.path == "/start":
            self._redirect("/hop2")
        elif self.path == "/hop2":
            self._redirect("/final")
        elif self.path == "/final":
            self._html(200, "<html><body>final</body></html>")
        elif self.path == "/stealth-check":
            self._html(
                200,
                "<html><body><script>"
                "document.documentElement.setAttribute('data-webdriver', "
                "String(navigator.webdriver));"
                "document.documentElement.setAttribute("
                "'data-has-chrome', String(!!window.chrome));"
                "</script></body></html>",
            )
        elif self.path == "/driver":
            self._html(
                200,
                f"""<html><body><script>
fetch('/ok').catch(() => {{}});
fetch('/missing').catch(() => {{}});
fetch('http://127.0.0.1:{self.closed_port}/').catch(() => {{}});
let n = 0;
const es = new EventSource('/sse');
es.onmessage = () => {{
    n += 1;
    if (n >= 3) {{
        es.close();
        document.documentElement.setAttribute('data-sse-done', 'true');
    }}
}};
</script></body></html>""",
            )
        else:
            self._html(404, "<html><body>not found</body></html>")

    def _sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for i in range(3):
                self.wfile.write(f"data: msg-{i}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.1)
            time.sleep(0.5)  # give the client time to close() cleanly before we would
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client closed its end once satisfied -- expected, not a failure

    def _html(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def log_message(self, *args: object) -> None:  # silence stdout noise during the run
        pass


@pytest.fixture
def network_capture_fixture_server() -> Iterator[str]:
    _NetworkCaptureFixtureHandler.closed_port = _find_closed_port()
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), _NetworkCaptureFixtureHandler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            server.shutdown()
            thread.join()


def test_capture_network_does_not_flip_webdriver_or_chrome_signals(
    network_capture_fixture_server,
) -> None:
    """#182's TRUE, narrow claim: turning capture_network on does not flip
    navigator.webdriver / window.chrome specifically (read via a DOM attribute the fixture
    page writes itself -- page.evaluate runs in an isolated world under Patchright and can't
    read page-script globals back). These two signals are controlled by Chromium LAUNCH
    FLAGS (--disable-blink-features=AutomationControlled, no --enable-automation), not by
    which CDP domains are enabled -- so this test would still pass even if capture_network
    sent Runtime.enable/Console.enable, and is NOT the guard against that. The actual guard
    against ever sending those is test_attach_network_capture_sends_only_network_enable in
    tests/test_patchright_backend.py, which pins the exact cdp.send call list. This e2e test
    is a real-browser sanity check of these two specific signals only, not a general
    detectability claim (see RenderOptions.capture_network's docstring for the UNVERIFIED
    scope)."""
    url = f"{network_capture_fixture_server}/stealth-check"

    with render_session(url) as s_off:
        off_webdriver = s_off.page.locator("html").get_attribute("data-webdriver")
        off_chrome = s_off.page.locator("html").get_attribute("data-has-chrome")

    with render_session(url, capture_network=True) as s_on:
        on_webdriver = s_on.page.locator("html").get_attribute("data-webdriver")
        on_chrome = s_on.page.locator("html").get_attribute("data-has-chrome")

    assert off_webdriver == on_webdriver == "false"
    assert off_chrome == on_chrome


def test_capture_network_records_ok_404_connrefused_and_sse(
    network_capture_fixture_server,
) -> None:
    """The main #182 capture: per-message SSE data and a connection-refused failure reason,
    against a real browser and a local fixture -- not a third-party site."""
    with render_session(
        f"{network_capture_fixture_server}/driver", capture_network=True, timeout=10.0
    ) as s:
        s.wait_for_selector("html[data-sse-done='true']")

    urls = [str(e["url"]) for e in s.network_log]
    assert any(u.endswith("/driver") for u in urls)
    assert any(u.endswith("/missing") for u in urls)
    assert any(u.endswith("/sse") for u in urls)

    missing_entry = next(e for e in s.network_log if str(e["url"]).endswith("/missing"))
    assert missing_entry["status"] == 404

    refused_entry = next(
        e for e in s.network_log if "CONNECTION_REFUSED" in str(e.get("error") or "")
    )
    assert refused_entry["status"] is None

    sse_entry = next(e for e in s.network_log if str(e["url"]).endswith("/sse"))
    sse_messages = sse_entry["sse_messages"]
    assert len(sse_messages) == 3
    assert [m["data"] for m in sse_messages] == ["msg-0", "msg-1", "msg-2"]
    assert s.network_log_truncated is False


def test_capture_network_records_one_entry_per_redirect_hop(
    network_capture_fixture_server,
) -> None:
    """#182 review bug fix, confirmed against a real browser: CDP reuses one requestId
    across an entire 302->302->200 chain, so this must record THREE entries (one per hop,
    each with its own URL and status, the finished hops naming the next via redirected_to)
    -- not one entry stuck with the first hop's URL and the last hop's status."""
    with render_session(f"{network_capture_fixture_server}/start", capture_network=True) as s:
        pass

    start = next(e for e in s.network_log if str(e["url"]).endswith("/start"))
    hop2 = next(e for e in s.network_log if str(e["url"]).endswith("/hop2"))
    final = next(e for e in s.network_log if str(e["url"]).endswith("/final"))

    assert start["status"] == 302
    assert str(start["redirected_to"]).endswith("/hop2")
    assert hop2["status"] == 302
    assert str(hop2["redirected_to"]).endswith("/final")
    assert final["status"] == 200
    assert "redirected_to" not in final


def test_capture_network_coexists_with_har_route_and_network_failures(
    tmp_path, network_capture_fixture_server
) -> None:
    """Stealth-safety condition: the extra CDP session must not break HAR recording,
    page.route, or the existing page.on(...)-based capture_network_failures when all are
    active together on the same page."""
    har_path = tmp_path / "coexist.har"
    routed_urls: list[str] = []

    def _on_route(route: object) -> None:
        routed_urls.append(route.request.url)  # type: ignore[attr-defined]
        route.continue_()  # type: ignore[attr-defined]

    with render_session(
        f"{network_capture_fixture_server}/driver",
        capture_network=True,
        record_har_path=str(har_path),
        timeout=10.0,
    ) as s:
        s.wait_for_selector("html[data-sse-done='true']")
        s.page.route("**/ok", _on_route)
        s.page.goto(f"{network_capture_fixture_server}/ok", wait_until="domcontentloaded")

    assert routed_urls  # page.route still fires
    assert any(str(e["url"]).endswith("/missing") for e in s.network_log)  # CDP capture intact
    assert any(e.get("status") == 404 for e in s.network_failures)  # page.on(...) capture intact
    assert har_path.exists()
    har = json.loads(har_path.read_text())
    assert len(har["log"]["entries"]) >= 1  # HAR recording intact
