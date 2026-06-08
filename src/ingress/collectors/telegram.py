"""
Telegram collector (public channels only).

Uses Telethon when credentials are supplied. The collector only reads public
channels the operator names explicitly and applies an optional keyword filter.

Also supports offline ingestion from Telegram Desktop exports (result.json)
or JSONL dumps of messages for use as an analysis platform with data from
authorized external collection.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
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
        self.diagnostics: list[str] = []

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

    def collect_from_file(self, path: str | Path, *, format: str | None = None, limit: Optional[int] = None) -> list[Artifact]:
        """
        Ingest Telegram messages from a local export file (offline / authorized archive).

        Supports:
          - Telegram Desktop export (result.json containing "messages" list)
          - JSONL file where each line is a message dict with 'text', 'id', 'date', optional 'channel'
          - format="telegram-export" or "jsonl" to force

        This lets Ingress serve as the fusion/analysis layer for data collected
        by external authorized means (exports, other Telegram tools, etc.).
        """
        p = Path(path)
        fmt = (format or "").lower()

        if fmt == "telegram-export" or "result.json" in p.name or p.suffix == ".json":
            return self._collect_from_telegram_export(p, limit=limit)

        if fmt == "jsonl" or p.suffix == ".jsonl":
            return self._collect_from_jsonl_messages(p, limit=limit)

        # Try to auto-detect
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
                if isinstance(data, dict) and "messages" in data:
                    return self._collect_from_telegram_export(p, limit=limit)
            except Exception:
                pass
            # fallback jsonl
            return self._collect_from_jsonl_messages(p, limit=limit)

        self.diagnostics.append(f"Unsupported or unreadable Telegram export: {p}")
        return []

    def _collect_from_telegram_export(self, path: Path, limit: Optional[int] = None) -> list[Artifact]:
        artifacts: list[Artifact] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            messages = data.get("messages", []) if isinstance(data, dict) else []
            channel = data.get("name") or path.stem if isinstance(data, dict) else path.stem

            for i, msg in enumerate(messages):
                if limit is not None and len(artifacts) >= limit:
                    break
                if not isinstance(msg, dict):
                    continue
                text = msg.get("text") or ""
                if isinstance(text, list):  # Telegram export can have rich text as list
                    text = " ".join(str(part.get("text", part)) if isinstance(part, dict) else str(part) for part in text)
                if not str(text).strip():
                    continue
                if self.keywords and not any(kw in str(text).lower() for kw in self.keywords):
                    continue

                msg_id = msg.get("id") or i
                date_str = msg.get("date")
                msg_date = None
                if date_str:
                    try:
                        msg_date = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
                    except Exception:
                        pass

                # Allow per-message channel override
                ch = msg.get("channel") or channel
                artifacts.append(self._message_to_artifact(ch, int(msg_id), str(text), msg_date))
        except Exception as exc:
            self.diagnostics.append(f"Failed to parse Telegram export {path}: {exc}")
        return artifacts

    def _collect_from_jsonl_messages(self, path: Path, limit: Optional[int] = None) -> list[Artifact]:
        artifacts: list[Artifact] = []
        try:
            with path.open(encoding="utf-8") as fh:
                for line_number, line in enumerate(fh, start=1):
                    if limit is not None and len(artifacts) >= limit:
                        break
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        msg = json.loads(text)
                    except json.JSONDecodeError as exc:
                        self.diagnostics.append(f"{path}:{line_number}: invalid JSON: {exc}")
                        continue
                    if not isinstance(msg, dict):
                        continue
                    content = msg.get("text") or msg.get("message") or ""
                    if not str(content).strip():
                        continue
                    if self.keywords and not any(kw in str(content).lower() for kw in self.keywords):
                        continue

                    ch = msg.get("channel") or msg.get("peer") or path.stem
                    mid = msg.get("id") or msg.get("message_id") or line_number
                    date = None
                    for k in ("date", "timestamp", "time"):
                        if k in msg:
                            try:
                                date = datetime.fromisoformat(str(msg[k]).replace("Z", "+00:00"))
                                break
                            except Exception:
                                pass
                    artifacts.append(self._message_to_artifact(str(ch), int(mid), str(content), date))
        except Exception as exc:
            self.diagnostics.append(f"Failed to parse Telegram JSONL {path}: {exc}")
        return artifacts
