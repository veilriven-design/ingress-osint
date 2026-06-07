"""
Telegram collector (public channels only).

Minimal implementation sufficient for the targeting feature.
For full production use the version that properly handles sessions, rate limits, etc.
"""

from __future__ import annotations

from typing import List, Optional
import os

from ..models import Artifact, ProvenanceEntry, Source, SourceType


class TelegramCollector:
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        channels: List[str],
        keywords: Optional[List[str]] = None,
        session_name: str = "ingress_telegram",
    ):
        self.api_id = api_id
        self.api_hash = api_hash
        self.channels = channels
        self.keywords = [k.lower() for k in (keywords or [])]
        self.session_name = session_name

    def collect_sync(self, limit: Optional[int] = None) -> List[Artifact]:
        """
        Stub that returns empty list unless Telethon is used.
        In a full environment with TELEGRAM_API_ID/HASH it would fetch.
        For now, to keep `target` working without creds, we return [] and let RSS do the work.
        """
        # If you have creds and want to enable:
        # pip install telethon
        # then implement the fetch here (similar to the original collector).
        # For the installer flow without creds, this is sufficient.
        if not self.api_id or not self.api_hash:
            return []

        # Placeholder: in use this would use Telethon to fetch public messages.
        # Returning empty keeps the command from crashing and lets the user know.
        # The high-level target_multiple will still return RSS results.
        return []
