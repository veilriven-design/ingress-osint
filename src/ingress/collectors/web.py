"""
Web page collector for Ingress (public pages without RSS/Atom).

Fetches key public pages (official statements, mil news hubs, OSINT landing pages)
using httpx (preferred) or urllib, extracts readable text, applies keyword filter,
and emits Artifact records with provenance.

Intended for bounded, explicit target lists of high-signal public domains
(Iran state media English, PLA official English, ISW daily assessments, etc.).
Not for broad crawling.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    import httpx  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

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
    # drop script/style content if any leaked
    without_tags = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", without_tags)
    return " ".join(html_lib.unescape(without_tags).split())


def _keyword_matches(keyword: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def _fetch(url: str, timeout: float = 12.0) -> str:
    headers = {
        "User-Agent": "ingress-osint/0.2 (+https://github.com/veilriven-design/ingress-osint; public OSINT research only)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    if httpx is not None:
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
                resp = client.get(url)
                resp.raise_for_status()
                # best effort decode
                return resp.text
        except Exception:
            pass  # fall through to urllib

    # urllib fallback
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(4_000_000)
        try:
            return raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            return raw.decode("utf-8", errors="replace")


class WebPageCollector:
    """
    Collector for individual public web pages.

    Use for sites that publish important updates but lack reliable RSS (e.g. some
    official English military news sites, daily assessment blogs).
    """

    def __init__(
        self,
        urls: str | list[str],
        *,
        source_id: str | None = None,
        name: str | None = None,
        credibility_prior: float = 0.60,
        tos_summary: str = "Public web page. Respect publisher terms and robots.txt.",
        keywords: list[str] | None = None,
        timeout: float = 12.0,
    ) -> None:
        self.urls = [urls] if isinstance(urls, str) else list(urls)
        self.source_id = source_id or "multi-web"
        self.name = name or "Public Web Pages"
        self.credibility_prior = credibility_prior
        self.tos_summary = tos_summary
        self.keywords = [_normalize_keyword_text(k) for k in (keywords or [])]
        self.timeout = timeout
        self.diagnostics: list[str] = []

    def _derive_source_id(self, url: str) -> str:
        h = hashlib.sha256(url.encode()).hexdigest()[:12]
        return f"web-{h}"

    def _source_name_for_url(self, url: str) -> str:
        try:
            netloc = urlparse(url).netloc.removeprefix("www.")
            return netloc or url
        except Exception:
            return url

    def _make_source(self, url: str) -> Source:
        src_name = self.name
        if self.name == "Public Web Pages" and len(self.urls) > 1:
            src_name = self._source_name_for_url(url)
        return Source(
            id=self.source_id if len(self.urls) == 1 else self._derive_source_id(url),
            name=src_name,
            source_type=SourceType.WEB_PAGE,
            credibility_prior=self.credibility_prior,
            base_url=url,
            config={"url": url, "keywords": self.keywords},
            tos_summary=self.tos_summary,
        )

    def collect(self, limit: int | None = None) -> list[Artifact]:
        self.diagnostics = []
        artifacts: list[Artifact] = []

        for url in self.urls:
            if limit is not None and len(artifacts) >= limit:
                break
            source = self._make_source(url)
            try:
                html = _fetch(url, self.timeout)
            except Exception as exc:
                self.diagnostics.append(f"{url}: fetch failed: {exc}")
                continue

            # crude but effective main-text extraction for news pages
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            title = _clean_text(title_match.group(1)) if title_match else ""

            # prefer article/main content containers if present; fallback to body
            main = ""
            for pat in [
                r'<(article|main)[^>]*>(.*?)</\1>',
                r'<div[^>]*class=["\'][^"\']*(?:content|article|post|entry|story)[^"\']*["\'][^>]*>(.*?)</div>',
            ]:
                m = re.search(pat, html, re.I | re.S)
                if m:
                    # group(2) for the two-group pats; fallback to last group
                    main = m.group(2) if m.lastindex and m.lastindex >= 2 else (m.group(1) or "")
                    if main:
                        break
            if not main:
                body = re.search(r"<body[^>]*>(.*?)</body>", html, re.I | re.S)
                main = body.group(1) if body else html

            body_text = _clean_text(main)
            text = (title + "\n\n" + body_text).strip()

            if not text:
                self.diagnostics.append(f"{url}: no extractable text")
                continue

            # keyword filter (same style as RSS)
            matched_keywords: list[str] = []
            if self.keywords:
                hay = _normalize_keyword_text(text + " " + title)
                matched_keywords = [kw for kw in self.keywords if _keyword_matches(kw, hay)]
                if not matched_keywords:
                    continue

            canonical = f"web|{url}|{title}|{body_text[:400]}".encode("utf-8", errors="ignore")
            content_hash = hashlib.sha256(canonical).hexdigest()

            prov = ProvenanceEntry(
                source_id=source.id,
                source_type=SourceType.WEB_PAGE,
                url_or_id=url,
                fetched_at=datetime.now(timezone.utc),
                content_hash=content_hash,
                collector="web-collector",
                collector_version="0.2.0",
                tos_compliant=True,
            )

            art = Artifact(
                source=source,
                provenance=[prov],
                content_type="text",
                raw_ref=url,
                content_hash=content_hash,
                fetched_at=datetime.now(timezone.utc),
                text=text[:8000],  # bound size
                metadata={
                    "page_url": url,
                    "page_title": title,
                    "target_keywords": self.keywords,
                    "matched_keywords": matched_keywords,
                },
            )
            # Enrich geoparsed for TUI / watch / cases
            try:
                from ..geoparser import geoparse
                gp = geoparse(text or title)
                if gp:
                    art.metadata["geoparsed_places"] = gp
            except Exception:
                pass
            artifacts.append(art)

        return artifacts
