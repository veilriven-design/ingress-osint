"""
Telegram collector (public channels only).

Uses Telethon when credentials are supplied. The collector only reads public
channels the operator names explicitly and applies an optional keyword filter.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Optional

from ..models import Artifact, ProvenanceEntry, Source, SourceType


class TelegramCollector:
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        channels: list[str],
        keywords: Optional[list[str]] = None,
        session_name: str = "ingress_telegram",
    ) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.channels = channels
        self.keywords = [k.lower() for k in (keywords or [])]
        self.session_name = session_name

    def collect_sync(self, limit: Optional[int] = None) -> list[Artifact]:
        if not self.api_id or not self.api_hash:
            return []

        return asyncio.run(self.collect(limit=limit))

    async def collect(self, limit: Optional[int] = None) -> list[Artifact]:
        try:
            from telethon import TelegramClient  # type: ignore[import-untyped]
            from telethon.errors import FloodWaitError  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("Telegram ingest requires telethon. Install with: pip install -e '.[full]'") from exc

        artifacts: list[Artifact] = []
        per_channel_limit = limit or 100

        async with TelegramClient(self.session_name, self.api_id, self.api_hash) as client:
            for channel in self.channels:
                try:
                    async for message in client.iter_messages(channel, limit=per_channel_limit):
                        text = message.message or ""
                        if not text.strip():
                            continue
                        if self.keywords and not any(keyword in text.lower() for keyword in self.keywords):
                            continue
                        artifacts.append(self._message_to_artifact(channel, message.id, text, message.date))
                except FloodWaitError as exc:
                    if exc.seconds > 60:
                        raise RuntimeError(f"Telegram rate limit is too long to wait safely: {exc.seconds}s") from exc
                    await asyncio.sleep(exc.seconds)

        return artifacts

    def _message_to_artifact(
        self,
        channel: str,
        message_id: int,
        text: str,
        message_date: datetime | None,
    ) -> Artifact:
        fetched_at = datetime.now(timezone.utc)
        observed_at = message_date or fetched_at
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        source = Source(
            id=f"telegram-{channel.lower()}",
            name=f"Telegram: {channel}",
            source_type=SourceType.TELEGRAM,
            credibility_prior=0.55,
            base_url=f"https://t.me/{channel}",
            config={"channel": channel, "keywords": self.keywords},
            tos_summary="Public Telegram channel. Respect Telegram terms and channel policies.",
        )
        canonical = f"telegram|{channel}|{message_id}|{text[:500]}".encode(
            "utf-8",
            errors="ignore",
        )
        content_hash = hashlib.sha256(canonical).hexdigest()
        url = f"https://t.me/{channel}/{message_id}"
        provenance = ProvenanceEntry(
            source_id=source.id,
            source_type=SourceType.TELEGRAM,
            url_or_id=url,
            fetched_at=fetched_at,
            collector="telegram-collector",
            collector_version="0.1.0",
            content_hash=content_hash,
            tos_compliant=True,
        )
        return Artifact(
            source=source,
            provenance=[provenance],
            content_type="text",
            raw_ref=url,
            content_hash=content_hash,
            fetched_at=observed_at,
            text=text,
            metadata={"channel": channel, "message_id": message_id, "target_keywords": self.keywords},
        )
