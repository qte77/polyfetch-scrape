from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Response:
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes
    content_type: str | None
    backend: Literal["httpx", "curl_cffi", "playwright"]
    # Set to the Location target on a permanent redirect (301/308) so callers can
    # update stored URLs; None for non-permanent responses (temporary 302/303/307).
    permanent_redirect_to: str | None = None
