"""musl-libc detection for the browser (patchright) tier.

Patchright ships no ``musllinux`` wheel, so on Alpine/musl the browser tier cannot be
installed or launched. Consumers otherwise meet this as a confusing downstream failure
(an unresolvable dependency, or a cryptic Chromium launch error when the glibc wheel was
force-installed), so every browser-tier entry point calls
:func:`ensure_browser_tier_supported` first and fails loudly naming the workaround (#197).

The httpx and curl_cffi tiers are unaffected — they run fine on musl.
"""

import platform
import sys
from pathlib import Path

from polyfetch_scrape.errors import FetchError

# The musl dynamic loader, e.g. /lib/ld-musl-x86_64.so.1 — present on Alpine et al.
_MUSL_LOADER_GLOB = "ld-musl-*.so.1"
_MUSL_LOADER_DIRS = (Path("/lib"), Path("/usr/lib"))

MUSL_UNSUPPORTED_MSG = (
    "patchright publishes no musllinux wheel, so the browser (patchright) tier cannot run "
    "on musl libc (Alpine). Either run on a glibc image (e.g. python:3.12-slim, debian), "
    'or skip the browser tier: `--max-tier curl_cffi` (CLI) / `max_tier="curl_cffi"` '
    "(library). The httpx and curl_cffi tiers work on musl."
)


def is_musl() -> bool:
    """True when running on a musl-libc Linux (Alpine et al.).

    Two cheap, local, network-free signals: CPython does not report glibc, and the musl
    dynamic loader is on disk. Non-Linux platforms are never musl.
    """
    if sys.platform != "linux":
        return False
    if platform.libc_ver()[0] == "glibc":
        return False
    return any(any(directory.glob(_MUSL_LOADER_GLOB)) for directory in _MUSL_LOADER_DIRS)


def ensure_browser_tier_supported() -> None:
    """Raise ``FetchError`` naming the limitation + workaround when running on musl."""
    if is_musl():
        raise FetchError(f"browser tier unavailable: {MUSL_UNSUPPORTED_MSG}")
