"""
FastAPI web surface for Ingress.

The API exposes the same SQLite-backed artifacts and sightings used by the CLI.
Collection remains explicit and operator-driven; the browser app is the review
and monitoring surface over local storage and audit logs.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .config import get_db_url
from .sample_data import make_sample_records
from .storage import (
    ensure_schema,
    get_counts,
    get_recent_artifacts,
    get_sightings,
    insert_artifact,
    insert_sighting,
)

WEB_DIR = Path(__file__).with_name("web")
ASSETS_DIR = WEB_DIR / "assets"
INDEX_HTML = WEB_DIR / "index.html"

TARGETS = {"comprehensive": ["iran", "russia", "china"], "iran": ["iran"], "russia": ["russia"], "china": ["china"]}
TARGET_LABELS = {
    "comprehensive": "Comprehensive",
    "iran": "Iran",
    "russia": "Russia",
    "china": "China",
}
COUNTRY_CODES = {"iran": "IR", "russia": "RU", "china": "CN"}
COLOR_HEX = {"red": "#b42318", "yellow": "#b7791f", "blue": "#2563eb", "green": "#16833b"}
STATIC_DB_MESSAGE = (
    "GitHub Pages scheduled static dashboard; browser refresh reloads the latest "
    "published JSON, while local FastAPI provides live SQLite updates."
)


class IngestRequest(BaseModel):
    source_type: str = Field(..., examples=["rss"])
    url: str | None = Field(None, examples=["https://example.com/feed.xml"])


def _safe_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        return {}


def _artifact_timestamp(row: dict[str, Any]) -> datetime:
    value = str(row.get("fetched_at") or "")
    if value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _confidence(row: dict[str, Any], meta: dict[str, Any]) -> float:
    value = meta.get("confidence")
    if isinstance(value, int | float):
        return max(0.0, min(1.0, float(value)))
    key = str(row.get("content_hash") or row.get("id") or "")
    return round(0.70 + (hash(key) % 20) / 100.0, 2)


def _status(meta: dict[str, Any]) -> str:
    value = meta.get("verification_status") or meta.get("status")
    return str(value or "analyst_reviewed")


def _display_excerpt(text: str, meta: dict[str, Any], limit: int = 1400) -> str:
    cleaned = text
    for _ in range(6):
        cleaned = re.sub(r"\{[^{}]*\}", " ", cleaned)
    cleaned = re.sub(r"@media\s+[^{\n]+", " ", cleaned)
    cleaned = re.sub(r"document\.addEventListener[^.]{0,500}", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    title = str(meta.get("page_title") or "").strip()
    if title and cleaned.lower().startswith(title.lower()):
        cleaned = cleaned[len(title):].strip(" -|")

    segments = []
    for segment in re.split(r"(?<=[.!?])\s+|\s{2,}", cleaned):
        low = segment.lower()
        if any(
            marker in low
            for marker in (
                "schema.org",
                "@context",
                "font-size",
                "!important",
                "gb-container",
                "html,body",
                "applet,object",
                "var ",
            )
        ):
            continue
        segment = segment.strip()
        if len(segment) >= 24:
            segments.append(segment)
        if len(" ".join(segments)) >= limit:
            break

    cleaned = " ".join(segments) or ("" if title else cleaned)
    if title:
        cleaned = f"{title} - {cleaned}" if cleaned else title
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _latest_audit_logs(limit: int = 5) -> list[dict[str, Any]]:
    data_dir = Path("data")
    if not data_dir.exists():
        return []
    logs = sorted(
        data_dir.glob("ingress-*.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    items = []
    for path in logs[:limit]:
        stat = path.stat()
        items.append({
            "name": path.name,
            "path": str(path),
            "bytes": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        })
    return items


def _target_list(target: str) -> list[str]:
    return TARGETS.get(target, TARGETS["comprehensive"])


def _dashboard_signal(row: dict[str, Any], targets: list[str]) -> dict[str, Any] | None:
    from .cli import (
        apply_criticality,
        artifact_matches_focus,
        clean_display_text,
        display_target_for_signal,
        watch_terms,
    )

    meta = _safe_metadata(row.get("metadata"))
    text = clean_display_text(str(row.get("text") or ""))
    source = row.get("source_name") or row.get("source_id") or "unknown"
    raw_ref = row.get("raw_ref")
    if not artifact_matches_focus(meta, text, targets, source=source, raw_ref=raw_ref):
        return None
    ts = _artifact_timestamp(row)
    target = display_target_for_signal(meta, text, targets, source=source, raw_ref=raw_ref)
    content_hash = str(row.get("content_hash") or row.get("id") or "n/a")
    signal = {
        "id": str(row.get("id") or content_hash),
        "timestamp": ts.isoformat(),
        "time_label": ts.strftime("%H:%M"),
        "source": str(source),
        "source_type": str(row.get("source_type") or row.get("content_type") or "text"),
        "text": text,
        "target": target,
        "country_code": COUNTRY_CODES.get(str(target or "").lower(), "--"),
        "confidence": _confidence(row, meta),
        "status": _status(meta),
        "entities": watch_terms(meta, text, targets),
        "provenance": f"db:{content_hash[:8]}",
        "raw_ref": raw_ref,
        "metadata": meta,
    }
    apply_criticality(signal)
    signal["text"] = _display_excerpt(text, meta)
    signal["criticality_hex"] = COLOR_HEX.get(str(signal.get("criticality_color")), "#525252")
    return signal


def _dashboard_payload(target: str, limit: int, db_url: str | None) -> dict[str, Any]:
    url = db_url or get_db_url()
    ensure_schema(url)
    target_key = target if target in TARGETS else "comprehensive"
    targets = _target_list(target_key)
    rows = get_recent_artifacts(max(limit * 3, 60), url)
    signals = []
    for row in rows:
        signal = _dashboard_signal(row, targets)
        if signal is not None:
            signals.append(signal)
        if len(signals) >= limit:
            break

    country_counts = Counter(str(signal.get("target") or "unknown") for signal in signals)
    source_counts = Counter(str(signal.get("source") or "unknown") for signal in signals)
    term_counts: Counter[str] = Counter()
    criticality_counts = Counter(str(signal.get("criticality_label") or "routine") for signal in signals)
    for signal in signals:
        term_counts.update(str(term) for term in signal.get("entities", [])[:6])

    commands = {
        "sample": f"ingress ingest sample --db-url {url}",
        "watch_live": "ingress watch --live --db-url " + url,
        "target_ingest": "ingress ingest target --iran --russia --china --db-url " + url,
    }
    if target_key != "comprehensive":
        commands["watch_live"] = f"ingress watch --live --{target_key} --db-url {url}"
        commands["target_ingest"] = f"ingress ingest target --{target_key} --db-url {url}"

    storage_counts = get_counts(url)
    return {
        "status": "ok",
        "version": __version__,
        "target": target_key,
        "target_label": TARGET_LABELS[target_key],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_url": url,
        "counts": storage_counts,
        "summary": {
            "signals": len(signals),
            "countries": country_counts.most_common(),
            "sources": source_counts.most_common(8),
            "terms": term_counts.most_common(10),
            "criticality": criticality_counts.most_common(),
            "audit_logs": _latest_audit_logs(),
        },
        "commands": commands,
        "signals": signals,
    }


def static_dashboard_payload(
    target: str = "comprehensive",
    limit: int = 120,
    db_url: str | None = None,
    fallback_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a Pages-safe dashboard payload generated from the current SQLite store.

    If scheduled public-source collection returns no matching rows, keep the published
    page useful by falling back to the checked-in static snapshot.
    """
    payload = _dashboard_payload(target, limit, db_url)
    fallback = Path(fallback_path) if fallback_path else None
    if not payload.get("signals") and fallback and fallback.exists():
        try:
            loaded = json.loads(fallback.read_text())
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict) and loaded.get("signals"):
            payload = loaded

    payload["status"] = "static"
    payload["mode"] = "static"
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    payload["db_url"] = STATIC_DB_MESSAGE
    payload["refresh_interval_minutes"] = 15
    return payload


def export_static_dashboard(
    output_path: str | Path,
    target: str = "comprehensive",
    limit: int = 120,
    db_url: str | None = None,
    fallback_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write a Pages-safe dashboard JSON file and return the exported payload."""
    payload = static_dashboard_payload(target, limit, db_url, fallback_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def create_app() -> FastAPI:
    app = FastAPI(
        title="Ingress",
        version=__version__,
        summary="High-integrity OSINT signals as they enter open domains.",
    )

    if ASSETS_DIR.exists():
        app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        if not INDEX_HTML.exists():
            raise HTTPException(status_code=404, detail="Web app assets are missing.")
        return FileResponse(INDEX_HTML)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/artifacts")
    def artifacts(
        limit: int = Query(30, ge=1, le=500),
        db_url: str | None = Query(None),
    ) -> list[dict[str, Any]]:
        url = db_url or get_db_url()
        try:
            ensure_schema(url)
            return get_recent_artifacts(limit, url)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/sightings")
    def sightings(
        limit: int = Query(1000, ge=1, le=5000),
        db_url: str | None = Query(None),
    ) -> list[dict[str, Any]]:
        url = db_url or get_db_url()
        try:
            ensure_schema(url)
            return get_sightings(limit, url)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/dashboard")
    def dashboard(
        target: str = Query("comprehensive", pattern="^(comprehensive|iran|russia|china)$"),
        limit: int = Query(60, ge=1, le=250),
        db_url: str | None = Query(None),
    ) -> dict[str, Any]:
        try:
            return _dashboard_payload(target, limit, db_url)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/sample")
    def seed_sample(db_url: str | None = Query(None)) -> dict[str, int | str]:
        url = db_url or get_db_url()
        try:
            ensure_schema(url)
            inserted_artifacts = 0
            inserted_sightings = 0
            for artifact, sighting in make_sample_records():
                if insert_artifact(artifact, url):
                    inserted_artifacts += 1
                if insert_sighting(sighting, url):
                    inserted_sightings += 1
            return {
                "status": "ok",
                "inserted_artifacts": inserted_artifacts,
                "inserted_sightings": inserted_sightings,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/ingest")
    def ingest(request: IngestRequest) -> dict[str, str | None]:
        if request.source_type != "rss":
            raise HTTPException(
                status_code=400,
                detail="Only rss ingest is planned for the API skeleton. Use the CLI for collectors.",
            )
        return {
            "status": "not_started",
            "source_type": request.source_type,
            "url": request.url,
            "next_step": "Run `ingress ingest rss <url>` to keep collection auditable.",
        }

    return app


app = create_app()
