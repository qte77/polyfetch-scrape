from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class Response:
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes
    content_type: str | None
    backend: Literal["httpx", "curl_cffi", "patchright"]
    # Set to the Location target on a permanent redirect (301/308) so callers can
    # update stored URLs; None for non-permanent responses (temporary 302/303/307).
    permanent_redirect_to: str | None = None
    # PNG bytes when a screenshot was requested on the patchright tier; else None.
    screenshot: bytes | None = None
    # Path to the recorded .webm when record_video_dir was set (browser tier); else None.
    video_path: Path | None = None
    # Browser-tier diagnostics — opt-in via RenderOptions.capture_*; empty on the httpx/curl tiers.
    # NOTE: reflects only THIS process's network — a failure a real user hits (CORS / extension /
    # proxy) can read clean here. Force a known failure to trust it (AGENT_LEARNINGS #3).
    console_errors: list[str] = field(default_factory=list[str])
    network_failures: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    # Full request trace — every completed request as {url, method, status, duration_ms};
    # opt-in via RenderOptions.capture_network_log. status/duration_ms are None when the
    # request failed or the browser reported no timing.
    network_log: list[dict[str, object]] = field(default_factory=list[dict[str, object]])
    # Named PNGs from RenderOptions.screenshots (patchright tier); empty otherwise.
    screenshots: dict[str, bytes] = field(default_factory=dict[str, bytes])
