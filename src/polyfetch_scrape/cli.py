import base64
import json
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from enum import StrEnum
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from polyfetch_scrape.client import Browser, Tier, fetch
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.render_options import ColorScheme, RenderOptions
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy
from polyfetch_scrape.throttle import Throttle
from polyfetch_scrape.utils.discovery import DiscoveredSources, discover


class _TierChoice(StrEnum):
    """CLI choice for the tier flags — typer validates the value and shows it in --help.

    Values mirror ``client.Tier``; ``_as_tier`` bridges the validated choice to that Literal.
    """

    httpx = "httpx"
    curl_cffi = "curl_cffi"
    patchright = "patchright"


def _as_tier(choice: _TierChoice | None) -> Tier | None:
    """Validated choice → the ``Tier`` Literal (sound: values are exactly the Literal members)."""
    return cast("Tier | None", choice.value) if choice is not None else None


class _BrowserChoice(StrEnum):
    """CLI choice for ``--browser`` — typer validates the value and shows it in --help.

    Values mirror ``client.Browser``; ``_as_browser`` bridges the validated choice to that Literal.
    """

    chrome = "chrome"
    firefox = "firefox"


def _as_browser(choice: _BrowserChoice) -> Browser:
    """Validated choice → the ``Browser`` Literal (values are exactly the Literal members)."""
    return choice.value


class _ColorSchemeChoice(StrEnum):
    """CLI choice for ``--color-scheme`` — typer validates the value and shows it in --help.

    Values mirror ``RenderOptions.color_scheme``; ``_as_color_scheme`` bridges to that Literal.
    """

    light = "light"
    dark = "dark"
    no_preference = "no-preference"


def _as_color_scheme(choice: _ColorSchemeChoice | None) -> ColorScheme | None:
    """Validated choice → the ``ColorScheme`` Literal (values are exactly the Literal members)."""
    return cast("ColorScheme | None", choice.value) if choice is not None else None


def _parse_viewport(value: str) -> tuple[int, int]:
    """Parse a ``WxH`` viewport string (e.g. ``1280x720``) into ``(width, height)``."""
    parts = value.lower().split("x")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise typer.BadParameter(f"viewport must be WxH (e.g. 1280x720), got: {value}")
    return int(parts[0]), int(parts[1])


app = typer.Typer(
    add_completion=False,
    help="HTTP scraping CLI: httpx → curl_cffi → patchright fallback chain",
    no_args_is_help=True,
)


def _version_cb(value: bool) -> None:
    if value:
        typer.echo(_pkg_version("polyfetch-scrape"))
        raise typer.Exit()


@app.callback()
def main_callback(  # pyright: ignore[reportUnusedFunction]
    _version: Annotated[
        bool | None,
        typer.Option("--version", callback=_version_cb, is_eager=True, help="Show version"),
    ] = None,
) -> None:
    return None


def _summarize(resp: Response) -> dict[str, Any]:
    return {
        "url": resp.url,
        "status": resp.status,
        "backend": resp.backend,
        "bytes": len(resp.body),
        "content_type": resp.content_type,
    }


def _format_text(payload: dict[str, Any]) -> str:
    if "error_type" in payload:
        return f"{payload['url']}  →  ERROR  {payload['error_type']}: {payload['message']}"
    return (
        f"{payload['url']}  →  {payload['status']} [{payload['backend']}]  "
        f"{payload['bytes']} bytes  {payload['content_type'] or ''}"
    ).rstrip()


def _error_payload(url: str, exc: FetchError) -> dict[str, Any]:
    """Structured error for ``--json``: shared by ``fetch`` and ``bulk`` (see USING.md)."""
    return {
        "url": url,
        "error_type": type(exc).__name__,
        "status": exc.status,
        "message": str(exc),
    }


def _build_render_options(
    *,
    wait_until: str,
    wait_for_selector: str | None,
    wait_for_function: str | None,
    screenshot: str | None,
    device: str | None,
    viewport: str | None,
    color_scheme: _ColorSchemeChoice | None,
    user_agent: str | None,
    locale: str | None,
    video_out: Path | None,
) -> RenderOptions:
    return RenderOptions(
        wait_until=wait_until,  # type: ignore[arg-type]
        wait_for_selector=wait_for_selector,
        wait_for_function=wait_for_function,
        screenshot=screenshot,
        device=device,
        viewport=_parse_viewport(viewport) if viewport is not None else None,
        color_scheme=_as_color_scheme(color_scheme),
        user_agent=user_agent,
        locale=locale,
        record_video_dir=video_out,
    )


@app.command()
def fetch_cmd(
    url: str,
    method: str = "GET",
    timeout: float = 30.0,
    max_attempts: int = 3,
    browser: Annotated[
        _BrowserChoice,
        typer.Option("--browser", help="Impersonation profile for the curl_cffi tier."),
    ] = _BrowserChoice.chrome,
    wait_for_selector: str | None = None,
    wait_until: Annotated[
        str,
        typer.Option(
            "--wait-until",
            help="Browser load milestone: domcontentloaded|load|networkidle.",
        ),
    ] = "domcontentloaded",
    wait_for_function: Annotated[
        str | None,
        typer.Option(
            "--wait-for-function", help="Browser tier: wait until this JS predicate is truthy."
        ),
    ] = None,
    screenshot: Annotated[
        str | None,
        typer.Option(
            "--screenshot",
            help="Browser tier: PNG of 'viewport', 'full_page', or a CSS selector.",
        ),
    ] = None,
    screenshot_out: Annotated[
        Path | None,
        typer.Option("--screenshot-out", help="Write the --screenshot PNG to this path."),
    ] = None,
    device: Annotated[
        str | None,
        typer.Option(
            "--device", help="Browser tier: emulate a Patchright device preset (e.g. 'iPhone 13')."
        ),
    ] = None,
    viewport: Annotated[
        str | None,
        typer.Option("--viewport", help="Browser tier: WxH viewport, e.g. 1280x720."),
    ] = None,
    color_scheme: Annotated[
        _ColorSchemeChoice | None,
        typer.Option("--color-scheme", help="Browser tier: light|dark|no-preference."),
    ] = None,
    user_agent: Annotated[
        str | None,
        typer.Option("--user-agent", help="Browser tier: override the context User-Agent."),
    ] = None,
    locale: Annotated[
        str | None,
        typer.Option("--locale", help="Browser tier: BCP 47 locale, e.g. en-US."),
    ] = None,
    video_out: Annotated[
        Path | None,
        typer.Option(
            "--video-out",
            help="Browser tier: record a VP8 .webm of the session into this directory.",
        ),
    ] = None,
    tier: Annotated[
        _TierChoice | None,
        typer.Option(
            "--tier",
            help="Pin one backend and skip the fallback chain. "
            "Render flags only apply when the patchright tier runs.",
        ),
    ] = None,
    min_tier: Annotated[
        _TierChoice | None,
        typer.Option(
            "--min-tier", help="Start the fallback chain at this tier (skip cheaper ones)."
        ),
    ] = None,
    max_tier: Annotated[
        _TierChoice | None,
        typer.Option(
            "--max-tier",
            help="Cap escalation at this tier (e.g. curl_cffi = never launch a browser).",
        ),
    ] = None,
    etag: Annotated[
        str | None,
        typer.Option("--etag", help="Send If-None-Match with this validator (conditional GET)."),
    ] = None,
    if_modified_since: Annotated[
        str | None,
        typer.Option(
            "--if-modified-since",
            help="Send If-Modified-Since with this HTTP-date (conditional GET).",
        ),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit JSON instead of text")] = False,
    show_body: Annotated[
        bool,
        typer.Option("--show-body", help="Print the raw response body instead of the summary"),
    ] = False,
) -> None:
    """Fetch a single URL through the fallback chain."""
    policy = RetryPolicy(max_attempts=max_attempts)
    render = _build_render_options(
        wait_until=wait_until,
        wait_for_selector=wait_for_selector,
        wait_for_function=wait_for_function,
        screenshot=screenshot,
        device=device,
        viewport=viewport,
        color_scheme=color_scheme,
        user_agent=user_agent,
        locale=locale,
        video_out=video_out,
    )
    try:
        resp = fetch(
            url,
            method=method,
            timeout=timeout,
            retry=policy,
            browser=_as_browser(browser),
            tier=_as_tier(tier),
            min_tier=_as_tier(min_tier),
            max_tier=_as_tier(max_tier),
            etag=etag,
            last_modified=if_modified_since,
            render=render,
        )
    except FetchError as exc:
        if json_output:
            typer.echo(json.dumps(_error_payload(url, exc)))
        else:
            typer.echo(f"{type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc

    if screenshot_out is not None and resp.screenshot is not None:
        screenshot_out.write_bytes(resp.screenshot)

    if show_body:
        # Write the raw bytes verbatim: decoding to str dropped output on non-UTF-8 /
        # non-TTY stdout (redirect/pipe) and mangled binary bodies (#66).
        sys.stdout.buffer.write(resp.body)
        sys.stdout.buffer.flush()
        return

    payload = _summarize(resp)
    if json_output and resp.screenshot is not None:
        # Surface the patchright-tier PNG inline so env-borrow / agent consumers get it in
        # the JSON without --screenshot-out writing a file (#105). Absent when no screenshot.
        payload["screenshot_b64"] = base64.b64encode(resp.screenshot).decode("ascii")
    if json_output and resp.video_path is not None:
        # Surface the recorded .webm's exact path so --video-out consumers learn the
        # auto-generated filename (Patchright names it). Absent when not recording.
        payload["video_path"] = str(resp.video_path)
    typer.echo(json.dumps(payload) if json_output else _format_text(payload))


# Bind 'fetch' as the command name (function name kept distinct from the import)
app.registered_commands[-1].name = "fetch"


def _run_one(
    url: str, *, timeout: float, max_attempts: int, throttle: Throttle | None
) -> dict[str, Any]:
    try:
        resp = fetch(
            url, timeout=timeout, retry=RetryPolicy(max_attempts=max_attempts), throttle=throttle
        )
    except FetchError as exc:
        return _error_payload(url, exc)
    return _summarize(resp)


def _run_pool(
    urls: list[str],
    *,
    workers: int,
    timeout: float,
    max_attempts: int,
    throttle: Throttle | None,
    emit: Callable[[dict[str, Any]], None],
) -> None:
    """Fetch ``urls`` concurrently, emitting each result in submit order as it completes."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _run_one, url, timeout=timeout, max_attempts=max_attempts, throttle=throttle
            )
            for url in urls
        ]
        for fut in futures:
            emit(fut.result())


@app.command()
def bulk(
    file: Path,
    workers: int = 1,
    timeout: float = 30.0,
    max_attempts: int = 3,
    delay: Annotated[
        float,
        typer.Option(
            "--delay",
            help="Per-host polite spacing in seconds (min interval between same-host requests).",
        ),
    ] = 0.0,
    json_output: Annotated[
        bool, typer.Option("--json/--text", help="JSON-lines (default) or human text")
    ] = True,
) -> None:
    """Fetch URLs from FILE (one per line; blank lines and ``#`` comments skipped)."""
    stripped = (line.strip() for line in file.read_text().splitlines())
    urls = [line for line in stripped if line and not line.startswith("#")]
    # One shared throttle across the worker pool → per-host spacing holds under concurrency.
    throttle = Throttle(delay) if delay > 0 else None
    any_failed = False

    def _emit(payload: dict[str, Any]) -> None:
        nonlocal any_failed
        if "error_type" in payload:
            any_failed = True
        line = json.dumps(payload) if json_output else _format_text(payload)
        typer.echo(line)

    if workers <= 1:
        for url in urls:
            _emit(_run_one(url, timeout=timeout, max_attempts=max_attempts, throttle=throttle))
    else:
        _run_pool(
            urls,
            workers=workers,
            timeout=timeout,
            max_attempts=max_attempts,
            throttle=throttle,
            emit=_emit,
        )

    if any_failed:
        sys.exit(1)


def _format_discovery(d: DiscoveredSources) -> str:
    fields = (
        ("sitemaps", d.sitemaps),
        ("event_sitemaps", d.event_sitemaps),
        ("feeds", d.feeds),
        ("llms_txt", d.llms_txt),
        ("json_ld_types", d.json_ld_types),
    )
    lines = [d.url]
    lines += [
        f"  {name} ({len(vals)}): {', '.join(vals) if vals else '—'}" for name, vals in fields
    ]
    return "\n".join(lines)


@app.command()
def discover_cmd(
    url: str,
    json_output: Annotated[bool, typer.Option("--json", help="Emit JSON instead of text")] = False,
) -> None:
    """Discover structured entrypoints (sitemaps / feeds / llms.txt / JSON-LD types) for a URL."""
    try:
        found = discover(url)
    except ValueError as exc:  # SSRF guard: internal address (literal, resolved, or redirect)
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(asdict(found)) if json_output else _format_discovery(found))


# Bind 'discover' as the command name (function name kept distinct from the import)
app.registered_commands[-1].name = "discover"


def _chromium_ok() -> bool:  # pragma: no cover - launches a real browser; not unit-testable
    """True if headless Chromium launches (installed); False when the browser is missing.

    A local, network-free probe: launch and immediately close a headless Patchright Chromium.
    Any launch failure (most commonly the browser not being installed) reads as unhealthy.
    """
    from patchright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
    except Exception:
        return False
    return True


def _install_chromium() -> int:  # pragma: no cover - shells out to the patchright installer
    """Install Patchright's Chromium (``patchright install chromium``); return its exit code."""
    return subprocess.run(
        [sys.executable, "-m", "patchright", "install", "chromium"], check=False
    ).returncode


@app.command()
def doctor(
    fix: Annotated[bool, typer.Option("--fix", help="Install Chromium if it is missing.")] = False,
) -> None:
    """Check the Patchright Chromium the browser tier needs; ``--fix`` installs it if missing.

    Exits non-zero when Chromium is unavailable (and ``--fix`` was not given, or the install
    failed) so borrowed-venv consumers can gate their e2e on ``polyfetch doctor``.
    """
    if _chromium_ok():
        typer.echo("chromium: ok")
        return
    if not fix:
        typer.echo(
            "chromium: missing — run `polyfetch doctor --fix` (or `make setup_browsers`)", err=True
        )
        raise typer.Exit(1)
    typer.echo("chromium: missing — installing via patchright …")
    if _install_chromium() != 0:
        typer.echo("chromium: install failed", err=True)
        raise typer.Exit(1)
    typer.echo("chromium: ok (installed)")


# --------------------------------------------------------------------------- #
# Contrib: easter-hunt. The single point where core references contrib — wrapped
# in try/except so removing src/polyfetch_scrape/contrib/ leaves the core CLI
# fully functional. Core never imports contrib anywhere else.
# --------------------------------------------------------------------------- #
try:
    from polyfetch_scrape.contrib.easter_hunt import Finding, hunt
    from polyfetch_scrape.contrib.easter_hunt.seeds import WELL_KNOWN_PATHS

    easter_hunt_app = typer.Typer(
        no_args_is_help=True, help="Scan fetched pages for notable artifacts."
    )

    def _resolve_seeds(url: str | None, seeds_file: Path | None) -> list[str]:
        if url is not None and seeds_file is not None:
            raise typer.BadParameter("Provide a URL or --seeds-file, not both")
        if seeds_file is not None:
            try:
                text = seeds_file.read_text()
            except OSError as exc:
                raise typer.BadParameter(f"Cannot read seeds file: {exc}") from exc
            stripped = (line.strip() for line in text.splitlines())
            seeds = [line for line in stripped if line and not line.startswith("#")]
        elif url is not None:
            seeds = [url]
        else:
            raise typer.BadParameter("Provide a URL or --seeds-file")
        if not seeds:
            raise typer.BadParameter("No seeds to scan")
        for seed in seeds:
            if not seed.startswith(("http://", "https://")):
                raise typer.BadParameter(f"URL must be http(s): {seed}")
        return seeds

    def _format_finding(f: "Finding") -> str:
        # URL first (mirrors the fetch/bulk text format) so each line names its source.
        return (
            f"{f.url}  [{f.severity}] {f.category} @ {f.location}  "
            f"({f.confidence:.0%})  {f.snippet}"
        )

    @easter_hunt_app.command()
    def scan(
        url: Annotated[str | None, typer.Argument(help="Single URL to scan")] = None,
        seeds_file: Annotated[
            Path | None, typer.Option("--seeds-file", help="File of URLs, one per line")
        ] = None,
        include_wellknown: Annotated[
            bool,
            typer.Option(
                "--include-wellknown", help='Also sweep well-known paths (on top of the "/" probe)'
            ),
        ] = False,
        json_output: Annotated[
            bool, typer.Option("--json", help="Emit JSON instead of text")
        ] = False,
    ) -> None:
        """Scan one or more URLs for notable page artifacts."""
        seeds = _resolve_seeds(url, seeds_file)
        paths = ("/", *WELL_KNOWN_PATHS) if include_wellknown else ("/",)
        try:
            findings = hunt(seeds, paths=paths)
        except ValueError as exc:  # SSRF guard: internal address (literal, resolved, or redirect)
            raise typer.BadParameter(str(exc)) from exc

        if json_output:
            typer.echo(json.dumps([asdict(f) for f in findings]))
        else:
            for finding in findings:
                typer.echo(_format_finding(finding))

    app.add_typer(easter_hunt_app, name="easter-hunt")
except ModuleNotFoundError:  # pragma: no cover - contrib is an optional extra
    pass
