"""
Storage layer for Ingress (SQLite focused for the installer).

Provides ensure_schema, insert_artifact (with dedup), get_recent_artifacts, get_sightings.
For full Postgres + PostGIS use the implementation or alembic.
"""

import sqlite3
import json
from datetime import datetime
from typing import Any, Optional, List, Dict
from pathlib import Path

from .config import get_db_url
from .models import Artifact, Sighting


def _get_conn(db_url: Optional[str] = None):
    if hasattr(db_url, 'default'):
        db_url = db_url.default
    url = db_url or get_db_url()
    if url.startswith("sqlite:///"):
        path = url.replace("sqlite:///", "", 1)
        if path == ":memory:":
            conn = sqlite3.connect(":memory:")
        else:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(p))
        conn.row_factory = sqlite3.Row
        return conn
    else:
        raise NotImplementedError("Only sqlite:// urls are supported in this layer. "
                                  "Install with [storage] extra and use Postgres for full support.")


def ensure_schema(db_url: Optional[str] = None) -> None:
    conn = _get_conn(db_url)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                source_id TEXT,
                source_name TEXT,
                source_type TEXT,
                content_type TEXT,
                raw_ref TEXT,
                content_hash TEXT UNIQUE,
                fetched_at TEXT,
                text TEXT,
                metadata TEXT,
                media_path TEXT
            );

            CREATE TABLE IF NOT EXISTS provenance (
                artifact_id TEXT,
                source_id TEXT,
                source_type TEXT,
                url_or_id TEXT,
                fetched_at TEXT,
                collector TEXT,
                collector_version TEXT,
                content_hash TEXT,
                tos_compliant INTEGER,
                FOREIGN KEY(artifact_id) REFERENCES artifacts(id)
            );

            CREATE TABLE IF NOT EXISTS sightings (
                id TEXT PRIMARY KEY,
                timestamp TEXT,
                lat REAL,
                lon REAL,
                location_name TEXT,
                description TEXT,
                confidence REAL,
                confidence_level TEXT,
                verification_status TEXT,
                metadata TEXT
            );

            CREATE TABLE IF NOT EXISTS sighting_artifacts (
                sighting_id TEXT,
                artifact_id TEXT,
                FOREIGN KEY(sighting_id) REFERENCES sightings(id),
                FOREIGN KEY(artifact_id) REFERENCES artifacts(id)
            );
        """)
        conn.commit()
    finally:
        conn.close()


def insert_artifact(artifact: Artifact, db_url: Optional[str] = None) -> bool:
    """Insert if content_hash not seen. Returns True if inserted."""
    conn = _get_conn(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM artifacts WHERE content_hash = ?", (artifact.content_hash,))
        if cur.fetchone():
            return False

        cur.execute("""
            INSERT INTO artifacts (id, source_id, source_name, source_type, content_type,
                                   raw_ref, content_hash, fetched_at, text, metadata, media_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            artifact.id,
            artifact.source.id,
            artifact.source.name,
            str(artifact.source.source_type),
            artifact.content_type,
            artifact.raw_ref,
            artifact.content_hash,
            artifact.fetched_at.isoformat() if artifact.fetched_at else None,
            artifact.text,
            json.dumps(artifact.metadata) if artifact.metadata else "{}",
            artifact.media_path,
        ))

        for p in artifact.provenance:
            cur.execute("""
                INSERT INTO provenance (artifact_id, source_id, source_type, url_or_id,
                                        fetched_at, collector, collector_version, content_hash, tos_compliant)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                artifact.id,
                p.source_id,
                str(p.source_type),
                p.url_or_id,
                p.fetched_at.isoformat() if p.fetched_at else None,
                p.collector,
                p.collector_version,
                p.content_hash,
                1 if p.tos_compliant else 0,
            ))

        conn.commit()
        return True
    finally:
        conn.close()


def get_recent_artifacts(limit: int = 30, db_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return recent artifacts as list of dicts for the TUI/watch."""
    conn = _get_conn(db_url)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, source_id, source_name, source_type, content_type, raw_ref,
                   content_hash, fetched_at, text, metadata, media_path
            FROM artifacts
            ORDER BY fetched_at DESC
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_sightings(limit: int = 1000, db_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return sightings joined with artifacts for export."""
    conn = _get_conn(db_url)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.id, s.timestamp, s.lat, s.lon, s.location_name, s.description,
                   s.confidence, s.confidence_level, s.verification_status, s.metadata,
                   GROUP_CONCAT(sa.artifact_id) as artifact_ids
            FROM sightings s
            LEFT JOIN sighting_artifacts sa ON s.id = sa.sighting_id
            GROUP BY s.id
            ORDER BY s.timestamp DESC
            LIMIT ?
        """, (limit,))
        rows = []
        for row in cur.fetchall():
            d = dict(row)
            if d.get("artifact_ids"):
                d["artifact_ids"] = d["artifact_ids"].split(",")
            else:
                d["artifact_ids"] = []
            if d.get("metadata"):
                try:
                    d["metadata"] = json.loads(d["metadata"])
                except:
                    d["metadata"] = {}
            else:
                d["metadata"] = {}
            rows.append(d)
        return rows
    finally:
        conn.close()


def insert_sighting(sighting: Sighting, db_url: Optional[str] = None) -> bool:
    """Insert a sighting and link artifacts."""
    conn = _get_conn(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM sightings WHERE id = ?", (sighting.id,))
        if cur.fetchone():
            return False

        cur.execute("""
            INSERT INTO sightings (id, timestamp, lat, lon, location_name, description,
                                   confidence, confidence_level, verification_status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sighting.id,
            sighting.timestamp.isoformat(),
            sighting.lat,
            sighting.lon,
            sighting.location_name,
            sighting.description,
            sighting.confidence,
            sighting.confidence_level.value if hasattr(sighting.confidence_level, 'value') else str(sighting.confidence_level),
            sighting.verification_status.value if hasattr(sighting.verification_status, 'value') else str(sighting.verification_status),
            json.dumps(sighting.metadata) if sighting.metadata else "{}",
        ))

        for aid in sighting.artifact_ids:
            cur.execute("""
                INSERT INTO sighting_artifacts (sighting_id, artifact_id) VALUES (?, ?)
            """, (sighting.id, aid))

        conn.commit()
        return True
    finally:
        conn.close()
