"""
Collector plugins for Ingress.

Each collector is responsible for turning open-domain signals into
Artifact (with full ProvenanceEntry chain) model instances.

Collectors should be:
- Targeted / rate-limited
- Respectful of ToS (documented in the source's tos_summary)
- Produce high-quality provenance
"""

from __future__ import annotations

from .network import NetworkTelemetryCollector
from .rss import RSSCollector
from .telegram import TelegramCollector
from .web import WebPageCollector
from .x import XCollector
from ..targeting import get_iran_config, get_russia_config, get_china_config, get_target_config

__all__ = [
    "NetworkTelemetryCollector",
    "RSSCollector",
    "TelegramCollector",
    "WebPageCollector",
    "XCollector",
    "get_iran_config",
    "get_russia_config",
    "get_china_config",
    "get_target_config",
]
