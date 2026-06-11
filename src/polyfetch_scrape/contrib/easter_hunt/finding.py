from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Finding:
    """A single notable artifact found on a fetched page.

    Pure value object. Detectors construct it from a ``Response``; ``url`` is
    always taken from ``response.url`` so a Finding is self-locating.
    """

    detector: str
    category: str  # recruiting | policy | stack | novelty | exposure
    severity: str  # info | notable | warn
    location: str  # e.g. "header:p3p" | "body:comment[3]" | "path:/.git/HEAD"
    snippet: str
    confidence: float  # 0.0–1.0
    url: str
