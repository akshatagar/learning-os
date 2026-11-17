"""extract(url) -> JSON with a short summary of what a reel says.

The Extractor protocol is the seam: the pipeline here is one implementation,
and a different model (or a different service) can replace it without the
inbox noticing.
"""
from typing import Protocol

from reel_inbox.extractor.schema import FIELDS


class Extractor(Protocol):
    def extract(self, url: str) -> dict:
        """Return a dict with exactly FIELDS, or raise ExtractionFailed."""


__all__ = ["Extractor", "FIELDS"]
