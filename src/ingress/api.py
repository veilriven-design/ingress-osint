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
    get_recent_artifacts_excluding,
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


def _sample_network_records() -> list[dict[str, Any]]:
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return [
        {
            "timestamp": stamp,
            "protocol": "tcp",
            "remote_domain": "api.chinamil.com.cn",
            "remote_port": 443,
            "process": "sample-browser",
            "state": "observed",
            "telemetry_source": "web-console-sample",
            "demo": True,
            "sni": "api.chinamil.com.cn",
            "ja3": "e7d705a3286e19ea42f587b344ee6865",
            "bytes_sent": 1280,
            "bytes_received": 8742,
            "duration_ms": 1240,
        },
        {
            "timestamp": stamp,
            "protocol": "udp",
            "remote_domain": "updates.mil.ru",
            "remote_port": 53,
            "process": "sample-resolver",
            "state": "dns-query",
            "telemetry_source": "web-console-sample",
            "demo": True,
            "dns_query": "updates.mil.ru",
            "qtype_name": "A",
        },
        {
            "timestamp": stamp,
            "protocol": "tcp",
            "remote_domain": "www.tasnimnews.com",
            "remote_port": 443,
            "process": "sample-fetch",
            "state": "observed",
            "telemetry_source": "web-console-sample",
            "demo": True,
            "http_host": "www.tasnimnews.com",
            "tls_sni": "www.tasnimnews.com",
        },
    ]


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
    rows = get_recent_artifacts_excluding(
        max(limit * 3, 60),
        url,
        excluded_source_types=("network_telemetry",),
        excluded_content_types=("network_telemetry",),
    )
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
        "network_monitor": "ingress monitor network --db-url " + url,
    }
    if target_key != "comprehensive":
        commands["watch_live"] = f"ingress watch --live --{target_key} --db-url {url}"
        commands["target_ingest"] = f"ingress ingest target --{target_key} --db-url {url}"
        commands["network_monitor"] = f"ingress monitor network --{target_key} --db-url {url}"

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


def _network_payload(target: str, limit: int, db_url: str | None) -> dict[str, Any]:
    url = db_url or get_db_url()
    ensure_schema(url)
    target_key = target if target in TARGETS else "comprehensive"
    targets = _target_list(target_key)
    # Network snapshots can be high-volume. Scan a wider local window so
    # unfocused connection-table noise does not hide target-domain telemetry.
    rows = get_recent_artifacts(max(limit * 20, 1000), url)
    observations: list[dict[str, Any]] = []
    domain_counts: Counter[str] = Counter()
    protocol_counts: Counter[str] = Counter()
    port_counts: Counter[str] = Counter()
    process_counts: Counter[str] = Counter()

    for row in rows:
        source_type = str(row.get("source_type") or "")
        content_type = str(row.get("content_type") or "")
        if source_type != "network_telemetry" and content_type != "network_telemetry":
            continue
        signal = _dashboard_signal(row, targets)
        if signal is None:
            continue
        meta = signal.get("metadata") or {}
        network = {
            "remote_host": meta.get("remote_host"),
            "remote_domain": meta.get("remote_domain"),
            "remote_port": meta.get("remote_port"),
            "local_host": meta.get("local_host"),
            "local_port": meta.get("local_port"),
            "protocol": meta.get("protocol"),
            "process": meta.get("process"),
            "state": meta.get("state"),
            "telemetry_source": meta.get("telemetry_source"),
            "demo": bool(meta.get("demo")),
            "matched_network_indicators": meta.get("matched_network_indicators") or [],
            "schema": meta.get("compatibility_schema"),
            "enriched": meta.get("enriched"),
            "ja3": meta.get("ja3") or (meta.get("enriched") or {}).get("ja3"),
            "dns_query": meta.get("dns_query") or (meta.get("enriched") or {}).get("dns_query"),
            "bytes": {
                "sent": (meta.get("enriched") or {}).get("bytes_sent") or meta.get("bytes_sent"),
                "received": (meta.get("enriched") or {}).get("bytes_received") or meta.get("bytes_received"),
            },
        }
        signal["network"] = network
        observations.append(signal)
        domain_counts.update([str(network.get("remote_domain") or network.get("remote_host") or "unknown")])
        protocol_counts.update([str(network.get("protocol") or "unknown")])
        port_counts.update([str(network.get("remote_port") or "unknown")])
        process_counts.update([str(network.get("process") or "unknown")])
        if len(observations) >= limit:
            break

    return {
        "status": "ok",
        "version": __version__,
        "target": target_key,
        "target_label": TARGET_LABELS[target_key],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_url": url,
        "summary": {
            "observations": len(observations),
            "domains": domain_counts.most_common(10),
            "protocols": protocol_counts.most_common(),
            "remote_ports": port_counts.most_common(10),
            "processes": process_counts.most_common(10),
        },
        "commands": {
            "monitor_network": (
                f"ingress monitor network --{target_key} --db-url {url}"
                if target_key != "comprehensive"
                else f"ingress monitor network --db-url {url}"
            ),
            "import_jsonl": f"ingress monitor network --input telemetry.jsonl --db-url {url}",
        },
        "observations": observations,
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

    @app.get("/api/network")
    def network(
        target: str = Query("comprehensive", pattern="^(comprehensive|iran|russia|china)$"),
        limit: int = Query(60, ge=1, le=250),
        db_url: str | None = Query(None),
    ) -> dict[str, Any]:
        try:
            return _network_payload(target, limit, db_url)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/network/live")
    def network_live(
        target: str = Query("comprehensive", pattern="^(comprehensive|iran|russia|china)$"),
        limit: int = Query(100, ge=1, le=500),
        include_unfocused: bool = Query(False),
    ) -> dict[str, Any]:
        """
        Perform a *fresh live local snapshot* of this host's connections (lsof/ss/netstat)
        and return normalized network telemetry observations.

        This makes the web console able to show *real* host network activity
        (authorized local only) on demand, instead of only seeded or DB data.
        No packets are captured; only current connection metadata is read.
        """
        try:
            from .collectors.network import NetworkTelemetryCollector

            targets = _target_list(target)
            coll = NetworkTelemetryCollector(
                targets=targets,
                include_unfocused=include_unfocused,
                source_id="live-local-snapshot",
                name="Live Local Snapshot",
            )
            arts = coll.collect_local_snapshot(limit=limit)

            observations = []
            domain_counts: Counter[str] = Counter()
            protocol_counts: Counter[str] = Counter()
            port_counts: Counter[str] = Counter()
            process_counts: Counter[str] = Counter()
            for art in arts:
                m = art.metadata or {}
                network = {
                    "remote_host": m.get("remote_host"),
                    "remote_domain": m.get("remote_domain"),
                    "remote_port": m.get("remote_port"),
                    "local_host": m.get("local_host"),
                    "local_port": m.get("local_port"),
                    "protocol": m.get("protocol"),
                    "process": m.get("process"),
                    "state": m.get("state"),
                    "ja3": m.get("ja3"),
                    "dns_query": m.get("dns_query"),
                    "bytes": {"sent": m.get("bytes_sent"), "received": m.get("bytes_received")},
                    "matched_network_indicators": m.get("matched_network_indicators", []),
                    "telemetry_source": m.get("telemetry_source"),
                    "demo": bool(m.get("demo")),
                }
                obs = {
                    "id": str(art.id),
                    "timestamp": art.fetched_at.isoformat(),
                    "time_label": art.fetched_at.strftime("%H:%M:%S"),
                    "source": art.source.name,
                    "source_type": "network_telemetry",
                    "text": art.text,
                    "target": (m.get("target_countries") or [None])[0] or "unfocused",
                    "country_code": ({"iran": "IR", "russia": "RU", "china": "CN"}.get((m.get("target_countries") or [None])[0], "--")),
                    "confidence": m.get("confidence", 0.55),
                    "status": m.get("status", "live"),
                    "entities": m.get("entities", []),
                    "provenance": "live-local",
                    "raw_ref": art.raw_ref,
                    "metadata": m,
                    "network": network,
                }
                observations.append(obs)
                domain_counts.update([str(network.get("remote_domain") or network.get("remote_host") or "unknown")])
                protocol_counts.update([str(network.get("protocol") or "unknown")])
                port_counts.update([str(network.get("remote_port") or "unknown")])
                process_counts.update([str(network.get("process") or "unknown")])

            return {
                "status": "ok",
                "version": __version__,
                "mode": "live-local",
                "target": target,
                "target_label": TARGET_LABELS.get(target, TARGET_LABELS["comprehensive"]),
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "summary": {
                    "observations": len(observations),
                    "domains": domain_counts.most_common(10),
                    "protocols": protocol_counts.most_common(),
                    "remote_ports": port_counts.most_common(10),
                    "processes": process_counts.most_common(10),
                    "is_live": True,
                    "focused_only": not include_unfocused,
                    "note": "Fresh local connection-table snapshot. Focused on configured public target domains by default.",
                },
                "commands": {
                    "monitor_network": (
                        f"ingress monitor network --{target} --db-url {get_db_url()}"
                        if target != "comprehensive"
                        else f"ingress monitor network --db-url {get_db_url()}"
                    ),
                    "import_jsonl": f"ingress monitor network --input telemetry.jsonl --db-url {get_db_url()}",
                },
                "observations": observations,
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/network/sample")
    def seed_network_sample(
        target: str = Query("comprehensive", pattern="^(comprehensive|iran|russia|china)$"),
        db_url: str | None = Query(None),
    ) -> dict[str, int | str]:
        from .collectors.network import NetworkTelemetryCollector

        url = db_url or get_db_url()
        target_key = target if target in TARGETS else "comprehensive"
        try:
            ensure_schema(url)
            collector = NetworkTelemetryCollector(targets=_target_list(target_key))
            artifacts = collector.collect_from_records(_sample_network_records())
            inserted_artifacts = 0
            for artifact in artifacts:
                if insert_artifact(artifact, url):
                    inserted_artifacts += 1
            return {
                "status": "ok",
                "target": target_key,
                "parsed_artifacts": len(artifacts),
                "inserted_artifacts": inserted_artifacts,
            }
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
