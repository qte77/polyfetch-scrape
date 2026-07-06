import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Annotated, Any

import typer

from polyfetch_scrape.client import fetch
from polyfetch_scrape.errors import FetchError
from polyfetch_scrape.render_options import RenderOptions
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy

app = typer.Typer(
    add_completion=False,
    help="HTTP scraping CLI: httpx → curl_cffi → playwright fallback chain",
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


@app.command()
def fetch_cmd(
    url: str,
    method: str = "GET",
    timeout: float = 30.0,
    max_attempts: int = 3,
    browser: str = "chrome",
    wait_for_selector: str | None = None,
    wait_until: Annotated[
        str,
        typer.Option(
            "--wait-until",
            help="Playwright load milestone: domcontentloaded|load|networkidle.",
        ),
    ] = "domcontentloaded",
    wait_for_function: Annotated[
        str | None,
        typer.Option(
            "--wait-for-function", help="Playwright: wait until this JS predicate is truthy."
        ),
    ] = None,
    screenshot: Annotated[
        str | None,
        typer.Option(
            "--screenshot",
            help="Playwright: PNG of 'viewport' or a CSS selector; write via --screenshot-out.",
        ),
    ] = None,
    screenshot_out: Annotated[
        Path | None,
        typer.Option("--screenshot-out", help="Write the --screenshot PNG to this path."),
    ] = None,
    tier: Annotated[
        str | None,
        typer.Option(
            "--tier",
            help="Pin one backend (httpx|curl_cffi|playwright) and skip the fallback chain. "
            "Render flags only apply when the playwright tier runs.",
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
    render = RenderOptions(
        wait_until=wait_until,  # type: ignore[arg-type]
        wait_for_selector=wait_for_selector,
        wait_for_function=wait_for_function,
        screenshot=screenshot,
    )
    try:
        resp = fetch(
            url,
            method=method,
            timeout=timeout,
            retry=policy,
            browser=browser,  # type: ignore[arg-type]
            tier=tier,  # type: ignore[arg-type]
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
    typer.echo(json.dumps(payload) if json_output else _format_text(payload))


# Bind 'fetch' as the command name (function name kept distinct from the import)
app.registered_commands[-1].name = "fetch"


def _run_one(url: str, *, timeout: float, max_attempts: int) -> dict[str, Any]:
    try:
        resp = fetch(url, timeout=timeout, retry=RetryPolicy(max_attempts=max_attempts))
    except FetchError as exc:
        return _error_payload(url, exc)
    return _summarize(resp)


@app.command()
def bulk(
    file: Path,
    workers: int = 1,
    timeout: float = 30.0,
    max_attempts: int = 3,
    json_output: Annotated[
        bool, typer.Option("--json/--text", help="JSON-lines (default) or human text")
    ] = True,
) -> None:
    """Fetch URLs from FILE (one per line; blank lines and ``#`` comments skipped)."""
    stripped = (line.strip() for line in file.read_text().splitlines())
    urls = [line for line in stripped if line and not line.startswith("#")]
    any_failed = False

    def _emit(payload: dict[str, Any]) -> None:
        nonlocal any_failed
        if "error_type" in payload:
            any_failed = True
        line = json.dumps(payload) if json_output else _format_text(payload)
        typer.echo(line)

    if workers <= 1:
        for url in urls:
            _emit(_run_one(url, timeout=timeout, max_attempts=max_attempts))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_run_one, url, timeout=timeout, max_attempts=max_attempts)
                for url in urls
            ]
            for fut in futures:
                _emit(fut.result())

    if any_failed:
        sys.exit(1)


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
        except ValueError as exc:  # SSRF guard: literal internal IP
            raise typer.BadParameter(str(exc)) from exc

        if json_output:
            typer.echo(json.dumps([asdict(f) for f in findings]))
        else:
            for finding in findings:
                typer.echo(_format_finding(finding))

    app.add_typer(easter_hunt_app, name="easter-hunt")
except ModuleNotFoundError:  # pragma: no cover - contrib is an optional extra
    pass
