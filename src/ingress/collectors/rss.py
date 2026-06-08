"""
RSS / Atom collector for Ingress.

Uses feedparser (lightweight, robust).

Produces Artifact instances with rich provenance for every entry.
Deduplication is performed at storage time via content_hash.

Example usage:
    collector = RSSCollector("https://example.mil/feed.xml", source_id="rss-mod-mil")
    artifacts = collector.collect()
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import feedparser  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised by minimal installs
    feedparser = None  # type: ignore[assignment]

from ..models import Artifact, ProvenanceEntry, Source, SourceType


def _normalize_keyword_text(value: str) -> str:
    return (
        value.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .lower()
    )


def _clean_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html_lib.unescape(without_tags).split())


def _keyword_matches(keyword: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


class RSSCollector:
    """
    Collector for RSS/Atom feeds.

    The 'manifest' is currently the constructor args (url + optional metadata).
    In later PRs this can be driven from a registry of configured sources.
    """

    def __init__(
        self,
        feed_url: str | list[str],
        *,
        source_id: str | None = None,
        name: str | None = None,
        credibility_prior: float = 0.65,
        tos_summary: str = "Public RSS/Atom feed. Respect publisher terms.",
        keywords: list[str] | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.feed_urls = [feed_url] if isinstance(feed_url, str) else feed_url
        self.source_id = source_id or "multi-rss"
        self.name = name or "Multi RSS Target"
        self.credibility_prior = credibility_prior
        self.tos_summary = tos_summary
        self.keywords = [_normalize_keyword_text(k) for k in (keywords or [])]
        self.timeout = timeout
        self.diagnostics: list[str] = []

    def _parse_feed(self, url: str) -> Any:
        if url.lower().startswith(("http://", "https://")):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "ingress-osint/0.1 (+https://github.com/veilriven-design/ingress-osint)"},
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = resp.read(5_000_000)
                return feedparser.parse(payload)
            except Exception as exc:
                self.diagnostics.append(f"{url}: {exc}")
                return feedparser.parse("")
        return feedparser.parse(url)

    def _derive_source_id(self, url: str) -> str:
        # Stable short id from URL
        h = hashlib.sha256(url.encode()).hexdigest()[:12]
        return f"rss-{h}"

    def _source_name_for_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.netloc:
            return parsed.netloc.removeprefix("www.")
        return Path(url).name or self.name

    def _make_source(self, url: str) -> Source:
        source_name = self.name
        if self.name == "Multi RSS Target" and len(self.feed_urls) > 1:
            source_name = self._source_name_for_url(url)
        return Source(
            id=self.source_id if len(self.feed_urls) == 1 else self._derive_source_id(url),
            name=source_name,
            source_type=SourceType.RSS,
            credibility_prior=self.credibility_prior,
            base_url=url,
            config={"feed_url": url, "keywords": self.keywords},
            tos_summary=self.tos_summary,
        )

    def collect(self, since: datetime | None = None, limit: int | None = None) -> list[Artifact]:
        """
        Parse the feed(s) and return Artifact models (not yet persisted).
        Applies keyword filter if provided (for country targeting).

        since: optional datetime to skip older entries (best-effort).
        limit: stop after this many matching items (for speed on large feeds).
        """
        if feedparser is None:
            raise RuntimeError("RSS ingest requires feedparser. Install with: pip install -e '.[full]'")

        self.diagnostics = []
        artifacts: list[Artifact] = []

        for url in self.feed_urls:
            if limit is not None and len(artifacts) >= limit:
                break
            source = self._make_source(url)
            feed = self._parse_feed(url)
            bozo_exception = getattr(feed, "bozo_exception", None)
            if bozo_exception:
                self.diagnostics.append(f"{url}: {bozo_exception}")
            entries = list(getattr(feed, "entries", []) or [])
            if not entries:
                self.diagnostics.append(f"{url}: no RSS/Atom entries parsed")
                continue
            for entry in entries:
                if limit is not None and len(artifacts) >= limit:
                    break
                link = entry.get("link") or entry.get("id")
                title = _clean_text(entry.get("title", ""))
                summary = _clean_text(entry.get("summary", "") or entry.get("description", ""))
                published = entry.get("published_parsed") or entry.get("updated_parsed")

                if published:
                    try:
                        parts = list(published[:6])
                        ts = datetime(
                            int(parts[0]),
                            int(parts[1]),
                            int(parts[2]),
                            int(parts[3]),
                            int(parts[4]),
                            int(parts[5]),
                            tzinfo=timezone.utc,
                        )
                    except Exception:
                        ts = datetime.now(timezone.utc)
                else:
                    ts = datetime.now(timezone.utc)

                if since and ts < since:
                    continue

                text = (title + "\n\n" + summary).strip() if title or summary else (link or "")

                # Keyword filter for targeted countries (military terms)
                matched_keywords: list[str] = []
                if self.keywords:
                    text_lower = _normalize_keyword_text(text + " " + title)
                    matched_keywords = [kw for kw in self.keywords if _keyword_matches(kw, text_lower)]
                    if not matched_keywords:
                        continue

                canonical = f"{link}|{title}|{summary[:300]}".encode("utf-8", errors="ignore")
                content_hash = hashlib.sha256(canonical).hexdigest()

                prov = ProvenanceEntry(
                    source_id=source.id,
                    source_type=SourceType.RSS,
                    url_or_id=link,
                    fetched_at=datetime.now(timezone.utc),
                    content_hash=content_hash,
                    collector="rss-collector",
                    collector_version="0.1.0",
                    tos_compliant=True,
                )

                art = Artifact(
                    source=source,
                    provenance=[prov],
                    content_type="text",
                    raw_ref=link,
                    content_hash=content_hash,
                    fetched_at=ts,
                    text=text or None,
                    metadata={
                        "feed_title": getattr(feed.feed, "title", None),
                        "entry_id": entry.get("id"),
                        "tags": [t.get("term") for t in entry.get("tags", []) if isinstance(t, dict)],
                        "target_keywords": self.keywords,
                        "matched_keywords": matched_keywords,
                    },
                )
                artifacts.append(art)

        return artifacts
