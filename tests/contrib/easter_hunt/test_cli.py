"""CLI tests for `polyfetch easter-hunt scan`. hunt() is monkeypatched at the
name bound in cli.py (`polyfetch_scrape.cli.hunt`); the SSRF-rejection tests use
the real hunt() because the guard raises before any network call."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from polyfetch_scrape.cli import app
from polyfetch_scrape.contrib.easter_hunt.finding import Finding
from polyfetch_scrape.contrib.easter_hunt.seeds import WELL_KNOWN_PATHS

runner = CliRunner()

_HUNT = "polyfetch_scrape.cli.hunt"


def _finding(category: str = "recruiting") -> Finding:
    return Finding(
        detector="html_comments",
        category=category,
        severity="notable",
        location="body:comment[0]",
        snippet="<!-- we are hiring -->",
        confidence=0.9,
        url="https://x.test/",
    )


def test_scan_subcommand_is_registered_in_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "easter-hunt" in result.stdout


def test_scan_text_output_contains_finding_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_HUNT, lambda *a, **kw: [_finding()])

    result = runner.invoke(app, ["easter-hunt", "scan", "https://x.test"])

    assert result.exit_code == 0
    assert "https://x.test/" in result.stdout  # the source site must be shown per finding
    assert "recruiting" in result.stdout
    assert "body:comment[0]" in result.stdout
    assert "notable" in result.stdout


def test_scan_json_emits_array_with_all_finding_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_HUNT, lambda *a, **kw: [_finding()])

    result = runner.invoke(app, ["easter-hunt", "scan", "https://x.test", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert set(payload[0]) == {
        "detector",
        "category",
        "severity",
        "location",
        "snippet",
        "confidence",
        "url",
    }
    assert payload[0]["confidence"] == pytest.approx(0.9)


def test_scan_json_empty_findings_prints_empty_array(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_HUNT, lambda *a, **kw: [])

    result = runner.invoke(app, ["easter-hunt", "scan", "https://x.test", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []


def test_scan_zero_findings_exits_0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_HUNT, lambda *a, **kw: [])
    result = runner.invoke(app, ["easter-hunt", "scan", "https://x.test"])
    assert result.exit_code == 0


def test_scan_without_url_or_seeds_file_exits_2() -> None:
    result = runner.invoke(app, ["easter-hunt", "scan"])
    assert result.exit_code == 2


def test_scan_non_http_url_exits_2() -> None:
    result = runner.invoke(app, ["easter-hunt", "scan", "ftp://x.test/file"])
    assert result.exit_code == 2


def test_scan_url_and_seeds_file_together_exits_2(tmp_path: Path) -> None:
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("https://a.test\n")
    result = runner.invoke(
        app, ["easter-hunt", "scan", "https://x.test", "--seeds-file", str(seeds)]
    )
    assert result.exit_code == 2


def test_scan_seeds_file_passes_stripped_nonblank_seeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("https://a.test\n\n   https://b.test   \n")
    captured: dict[str, list[str]] = {}

    def spy(seeds_arg: list[str], **_kw: object) -> list[Finding]:
        captured["seeds"] = list(seeds_arg)
        return []

    monkeypatch.setattr(_HUNT, spy)

    result = runner.invoke(app, ["easter-hunt", "scan", "--seeds-file", str(seeds), "--json"])

    assert result.exit_code == 0
    assert captured["seeds"] == ["https://a.test", "https://b.test"]


def test_scan_empty_seeds_file_exits_2(tmp_path: Path) -> None:
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("\n   \n\n")
    result = runner.invoke(app, ["easter-hunt", "scan", "--seeds-file", str(seeds)])
    assert result.exit_code == 2


def test_scan_seeds_file_skips_comment_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A seeds file may be annotated with '#' comment lines (and blanks); only the
    # URL lines reach hunt().
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("# header comment\nhttps://a.test\n\n#  group note\nhttps://b.test\n")
    captured: dict[str, list[str]] = {}

    def spy(seeds_arg: list[str], **_kw: object) -> list[Finding]:
        captured["seeds"] = list(seeds_arg)
        return []

    monkeypatch.setattr(_HUNT, spy)

    result = runner.invoke(app, ["easter-hunt", "scan", "--seeds-file", str(seeds)])

    assert result.exit_code == 0
    assert captured["seeds"] == ["https://a.test", "https://b.test"]


def test_scan_default_paths_excludes_wellknown(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple[str, ...]] = {}

    def spy(_seeds: list[str], *, paths: tuple[str, ...]) -> list[Finding]:
        captured["paths"] = tuple(paths)
        return []

    monkeypatch.setattr(_HUNT, spy)
    runner.invoke(app, ["easter-hunt", "scan", "https://x.test"])
    assert captured["paths"] == ("/",)


def test_scan_include_wellknown_extends_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, tuple[str, ...]] = {}

    def spy(_seeds: list[str], *, paths: tuple[str, ...]) -> list[Finding]:
        captured["paths"] = tuple(paths)
        return []

    monkeypatch.setattr(_HUNT, spy)
    runner.invoke(app, ["easter-hunt", "scan", "https://x.test", "--include-wellknown"])
    assert captured["paths"] == ("/", *WELL_KNOWN_PATHS)


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://169.254.169.254/"])
def test_scan_literal_internal_ip_exits_2(url: str) -> None:
    # Real hunt(): the SSRF guard raises ValueError before any fetch; scan() must
    # surface it as a bad parameter (exit 2), not crash (exit 1).
    result = runner.invoke(app, ["easter-hunt", "scan", url])
    assert result.exit_code == 2


def test_scan_nonexistent_seeds_file_exits_2(tmp_path: Path) -> None:
    # A missing --seeds-file must be a clean bad parameter (exit 2), not an uncaught
    # FileNotFoundError (exit 1 + traceback).
    missing = tmp_path / "nope.txt"
    result = runner.invoke(app, ["easter-hunt", "scan", "--seeds-file", str(missing)])
    assert result.exit_code == 2
