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
from datetime import datetime, timezone

try:
    import feedparser  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - exercised by minimal installs
    feedparser = None  # type: ignore[assignment]

from ..models import Artifact, ProvenanceEntry, Source, SourceType


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
    ) -> None:
        self.feed_urls = [feed_url] if isinstance(feed_url, str) else feed_url
        self.source_id = source_id or "multi-rss"
        self.name = name or "Multi RSS Target"
        self.credibility_prior = credibility_prior
        self.tos_summary = tos_summary
        self.keywords = [k.lower() for k in (keywords or [])]
        self.diagnostics: list[str] = []

    def _derive_source_id(self, url: str) -> str:
        # Stable short id from URL
        h = hashlib.sha256(url.encode()).hexdigest()[:12]
        return f"rss-{h}"

    def _make_source(self) -> Source:
        return Source(
            id=self.source_id,
            name=self.name,
            source_type=SourceType.RSS,
            credibility_prior=self.credibility_prior,
            base_url=self.feed_urls[0] if self.feed_urls else None,  # type: ignore[arg-type]
            config={"feed_urls": self.feed_urls, "keywords": self.keywords},
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
        source = self._make_source()
        artifacts: list[Artifact] = []

        for url in self.feed_urls:
            if limit is not None and len(artifacts) >= limit:
                break
            feed = feedparser.parse(url)
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
                title = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")
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
                if self.keywords:
                    text_lower = text.lower() + " " + title.lower()
                    if not any(kw in text_lower for kw in self.keywords):
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
                    },
                )
                artifacts.append(art)

        return artifacts
