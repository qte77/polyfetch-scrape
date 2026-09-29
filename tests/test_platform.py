"""musl detection + the browser-tier platform gate (#197).

Patchright ships no ``musllinux`` wheel, so the browser (patchright) tier cannot be
installed or launched on Alpine/musl. These tests cover the three ``is_musl()``
branches (musl / glibc / non-Linux) and the gate that turns a musl host into a
loud, actionable ``FetchError`` instead of a cryptic import/launch failure.
"""

import sys
from pathlib import Path

import pytest

from polyfetch_scrape import _platform
from polyfetch_scrape.errors import FetchError


def _with_musl_loader(tmp_path: Path) -> tuple[Path, ...]:
    """A ``/lib``-alike directory containing the musl dynamic loader."""
    (tmp_path / "ld-musl-x86_64.so.1").touch()
    return (tmp_path,)


def test_is_musl_false_on_non_linux(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Loader present but the platform is not Linux → never musl (glibc_ver / the glob
    # are not even consulted; macOS and Windows are always glibc-irrelevant).
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(_platform, "_MUSL_LOADER_DIRS", _with_musl_loader(tmp_path))

    assert _platform.is_musl() is False


def test_is_musl_false_when_glibc_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_platform.platform, "libc_ver", lambda: ("glibc", "2.36"))
    monkeypatch.setattr(_platform, "_MUSL_LOADER_DIRS", _with_musl_loader(tmp_path))

    assert _platform.is_musl() is False


def test_is_musl_false_when_loader_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # platform.libc_ver() reports ('', '') on musl too (CPython doesn't recognise it), so
    # the loader-file check is the deciding signal. No loader present → not musl.
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_platform.platform, "libc_ver", lambda: ("", ""))
    monkeypatch.setattr(_platform, "_MUSL_LOADER_DIRS", (tmp_path, tmp_path / "nonexistent"))

    assert _platform.is_musl() is False


def test_is_musl_true_on_alpine_like(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_platform.platform, "libc_ver", lambda: ("", ""))
    monkeypatch.setattr(_platform, "_MUSL_LOADER_DIRS", _with_musl_loader(tmp_path))

    assert _platform.is_musl() is True


def test_ensure_browser_tier_supported_is_a_noop_off_musl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_platform, "is_musl", lambda: False)

    assert _platform.ensure_browser_tier_supported() is None


def test_ensure_browser_tier_supported_names_limitation_and_workaround(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_platform, "is_musl", lambda: True)

    with pytest.raises(FetchError) as excinfo:
        _platform.ensure_browser_tier_supported()

    message = str(excinfo.value)
    assert "musllinux" in message  # names the limitation
    assert "--max-tier curl_cffi" in message  # names the workaround
