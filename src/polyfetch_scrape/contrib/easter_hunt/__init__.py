"""easter_hunt: scan fetched pages for notable artifacts.

Public surface: ``hunt`` (orchestrator), ``Finding`` (value object), ``DETECTORS``
(default detector pack) and the ``Detector`` type alias.
"""

from polyfetch_scrape.contrib.easter_hunt.detectors import DETECTORS, Detector
from polyfetch_scrape.contrib.easter_hunt.finding import Finding
from polyfetch_scrape.contrib.easter_hunt.orchestrator import hunt

__all__ = ["DETECTORS", "Detector", "Finding", "hunt"]
