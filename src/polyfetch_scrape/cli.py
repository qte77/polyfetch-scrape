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
from polyfetch_scrape.response import Response
from polyfetch_scrape.retry import RetryPolicy
from polyfetch_scrape.sources import arxiv as arxiv_source

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
    if "error" in payload:
        return f"{payload['url']}  →  ERROR  {payload['error']}"
    return (
        f"{payload['url']}  →  {payload['status']} [{payload['backend']}]  "
        f"{payload['bytes']} bytes  {payload['content_type'] or ''}"
    ).rstrip()


@app.command()
def fetch_cmd(
    url: str,
    method: str = "GET",
    timeout: float = 30.0,
    max_attempts: int = 3,
    browser: str = "chrome",
    wait_for_selector: str | None = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit JSON instead of text")] = False,
) -> None:
    """Fetch a single URL through the fallback chain."""
    policy = RetryPolicy(max_attempts=max_attempts)
    try:
        resp = fetch(
            url,
            method=method,
            timeout=timeout,
            retry=policy,
            browser=browser,  # type: ignore[arg-type]
            wait_for_selector=wait_for_selector,
        )
    except FetchError as exc:
        typer.echo(f"FetchError: {exc}", err=True)
        raise typer.Exit(1) from exc

    payload = _summarize(resp)
    typer.echo(json.dumps(payload) if json_output else _format_text(payload))


# Bind 'fetch' as the command name (function name kept distinct from the import)
app.registered_commands[-1].name = "fetch"


def _run_one(url: str, *, timeout: float, max_attempts: int) -> dict[str, Any]:
    try:
        resp = fetch(url, timeout=timeout, retry=RetryPolicy(max_attempts=max_attempts))
    except FetchError as exc:
        return {"url": url, "error": f"{type(exc).__name__}: {exc}", "backend": None}
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
    """Fetch URLs read from FILE (one per line); emit one record per URL."""
    urls = [line.strip() for line in file.read_text().splitlines() if line.strip()]
    any_failed = False

    def _emit(payload: dict[str, Any]) -> None:
        nonlocal any_failed
        if "error" in payload:
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


# --- arxiv source subcommand ---

arxiv_app = typer.Typer(help="arXiv API wrappers", no_args_is_help=True)
app.add_typer(arxiv_app, name="arxiv")


@arxiv_app.command("get")
def arxiv_get(
    arxiv_id: str,
    timeout: float = 30.0,
    json_output: Annotated[bool, typer.Option("--json", help="Emit JSON instead of text")] = False,
) -> None:
    """Fetch an arXiv paper's metadata by id (e.g. 2301.00001)."""
    try:
        paper = arxiv_source.get(arxiv_id, timeout=timeout)
    except FetchError as exc:
        typer.echo(f"{type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(1) from exc

    if json_output:
        typer.echo(json.dumps(asdict(paper)))
        return

    typer.echo(f"arxiv:{paper.arxiv_id} — {paper.title!r}")
    typer.echo(f"authors: {', '.join(paper.authors)}")
    typer.echo(f"categories: {', '.join(paper.categories)}")
    typer.echo(f"published: {paper.published_at}")
    typer.echo(f"abs:     {paper.abs_url}")
    typer.echo(f"pdf:     {paper.pdf_url}")
