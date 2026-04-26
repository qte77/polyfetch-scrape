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
