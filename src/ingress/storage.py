import json
import sqlite3
from enum import Enum
from pathlib import Path
from typing import Any

from .config import get_db_url
from .models import Artifact, Sighting


def _coerce_db_url(db_url: str | None = None) -> str:
    url = db_url or get_db_url()
    if not isinstance(url, str):
        raise TypeError(f"Database URL must be a string, got {type(url).__name__}")
    return url


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _get_conn(db_url: str | None = None) -> sqlite3.Connection:
    url = _coerce_db_url(db_url)
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
    raise NotImplementedError(
        "Only sqlite:// URLs are supported by the current storage layer. "
        "Postgres/PostGIS is planned but not implemented in this build."
    )


def ensure_schema(db_url: str | None = None) -> None:
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
                entities TEXT,
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

        # Migrate schema for older DBs (add missing columns)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(artifacts)")
        cols = [row[1] for row in cur.fetchall()]
        if "source_name" not in cols:
            try:
                cur.execute("ALTER TABLE artifacts ADD COLUMN source_name TEXT")
                conn.commit()
            except Exception:
                pass
        if "media_path" not in cols:
            try:
                cur.execute("ALTER TABLE artifacts ADD COLUMN media_path TEXT")
                conn.commit()
            except Exception:
                pass

        cur.execute("PRAGMA table_info(sightings)")
        sighting_cols = [row[1] for row in cur.fetchall()]
        if "entities" not in sighting_cols:
            try:
                cur.execute("ALTER TABLE sightings ADD COLUMN entities TEXT")
                conn.commit()
            except Exception:
                pass
    finally:
        conn.close()


def insert_artifact(artifact: Artifact, db_url: str | None = None) -> bool:
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
            _enum_value(artifact.source.source_type),
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
                _enum_value(p.source_type),
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


def get_recent_artifacts(limit: int = 30, db_url: str | None = None) -> list[dict[str, Any]]:
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


def get_recent_artifacts_excluding(
    limit: int = 30,
    db_url: str | None = None,
    *,
    excluded_source_types: tuple[str, ...] = (),
    excluded_content_types: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Return recent artifacts while excluding high-volume side panels."""
    conn = _get_conn(db_url)
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if excluded_source_types:
            placeholders = ", ".join("?" for _ in excluded_source_types)
            clauses.append(f"COALESCE(source_type, '') NOT IN ({placeholders})")
            params.extend(excluded_source_types)
        if excluded_content_types:
            placeholders = ", ".join("?" for _ in excluded_content_types)
            clauses.append(f"COALESCE(content_type, '') NOT IN ({placeholders})")
            params.extend(excluded_content_types)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, source_id, source_name, source_type, content_type, raw_ref,
                   content_hash, fetched_at, text, metadata, media_path
            FROM artifacts
            {where}
            ORDER BY fetched_at DESC
            LIMIT ?
        """,
            params,
        )
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_counts(db_url: str | None = None) -> dict[str, int]:
    """Return basic storage counts for status/doctor commands."""
    conn = _get_conn(db_url)
    try:
        cur = conn.cursor()
        counts: dict[str, int] = {}
        for table in ("artifacts", "provenance", "sightings", "sighting_artifacts"):
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = int(cur.fetchone()[0])
        return counts
    finally:
        conn.close()


def get_sightings(limit: int = 1000, db_url: str | None = None) -> list[dict[str, Any]]:
    """Return sightings joined with artifacts for export."""
    conn = _get_conn(db_url)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT s.id, s.timestamp, s.lat, s.lon, s.location_name, s.entities, s.description,
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
                except json.JSONDecodeError:
                    d["metadata"] = {}
            else:
                d["metadata"] = {}
            if d.get("entities"):
                try:
                    d["entities"] = json.loads(d["entities"])
                except json.JSONDecodeError:
                    d["entities"] = []
            else:
                d["entities"] = []
            rows.append(d)
        return rows
    finally:
        conn.close()


def insert_sighting(sighting: Sighting, db_url: str | None = None) -> bool:
    """Insert a sighting and link artifacts."""
    conn = _get_conn(db_url)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM sightings WHERE id = ?", (sighting.id,))
        if cur.fetchone():
            return False

        cur.execute("""
            INSERT INTO sightings (id, timestamp, lat, lon, location_name, entities, description,
                                   confidence, confidence_level, verification_status, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sighting.id,
            sighting.timestamp.isoformat(),
            sighting.lat,
            sighting.lon,
            sighting.location_name,
            json.dumps(sighting.entities),
            sighting.description,
            sighting.confidence,
            _enum_value(sighting.confidence_level),
            _enum_value(sighting.verification_status),
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
