"""
X (Twitter) collector stub.

Implementation requires X API access (paid tiers as of 2024).
This is a no-op collector so that `from .x import XCollector` succeeds
and `ingress ingest target` etc. do not crash on import.
"""

from __future__ import annotations

from typing import List, Optional

from ..models import Artifact


class XCollector:
    def __init__(self, *args, **kwargs):
        pass

    def collect(self, *args, **kwargs) -> List[Artifact]:
        print("[yellow]X collector is a stub. Provide bearer token + implement for use.[/yellow]")
        return []
