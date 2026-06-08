"""
Deterministic local sample data.

These records are synthetic and clearly marked as samples. They give a fresh
local install enough data to exercise watch, delta, export, and case workflows
without pretending to have collected live evidence.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from .models import (
    Artifact,
    ConfidenceLevel,
    ProvenanceEntry,
    Sighting,
    Source,
    SourceType,
    VerificationStatus,
)


class SampleSignal(TypedDict):
    source_id: str
    source_name: str
    source_type: SourceType
    raw_ref: str
    text: str
    entities: list[str]
    location_name: str
    lat: float
    lon: float
    confidence: float
    status: VerificationStatus
    minutes_ago: int


SAMPLE_SIGNALS: list[SampleSignal] = [
    {
        "source_id": "sample-rss-defense",
        "source_name": "Sample Defense RSS",
        "source_type": SourceType.RSS,
        "raw_ref": "sample://rss/convoy-pokrovsk",
        "text": "Sample report: T-72 convoy sighted near Pokrovsk with two independent public posts.",
        "entities": ["T-72", "convoy", "Pokrovsk"],
        "location_name": "Pokrovsk",
        "lat": 48.282,
        "lon": 37.175,
        "confidence": 0.72,
        "status": VerificationStatus.ANALYST_REVIEWED,
        "minutes_ago": 20,
    },
    {
        "source_id": "sample-telegram-osint",
        "source_name": "Sample Telegram OSINT",
        "source_type": SourceType.TELEGRAM,
        "raw_ref": "sample://telegram/uav-belgorod",
        "text": "Sample channel post: UAV interception claims around Belgorod need corroboration.",
        "entities": ["UAV", "Belgorod"],
        "location_name": "Belgorod",
        "lat": 50.596,
        "lon": 36.587,
        "confidence": 0.58,
        "status": VerificationStatus.UNVERIFIED,
        "minutes_ago": 55,
    },
    {
        "source_id": "sample-media",
        "source_name": "Sample User Media",
        "source_type": SourceType.USER_UPLOAD,
        "raw_ref": "sample://media/vuhledar-grad",
        "text": "Sample media note: Grad launcher audio and visual clues mention Vuhledar.",
        "entities": ["Grad", "Vuhledar"],
        "location_name": "Vuhledar",
        "lat": 47.779,
        "lon": 37.25,
        "confidence": 0.66,
        "status": VerificationStatus.CORROBORATED,
        "minutes_ago": 90,
    },
]


def make_sample_records() -> list[tuple[Artifact, Sighting]]:
    now = datetime.now(timezone.utc)
    records: list[tuple[Artifact, Sighting]] = []

    for row in SAMPLE_SIGNALS:
        fetched_at = now - timedelta(minutes=row["minutes_ago"])
        canonical = f"{row['raw_ref']}|{row['text']}".encode("utf-8")
        content_hash = hashlib.sha256(canonical).hexdigest()
        source = Source(
            id=row["source_id"],
            name=row["source_name"],
            source_type=row["source_type"],
            credibility_prior=0.5,
            base_url=row["raw_ref"],
            config={"sample": True},
            tos_summary="Synthetic local sample data. Not collected evidence.",
        )
        provenance = ProvenanceEntry(
            source_id=source.id,
            source_type=source.source_type,
            url_or_id=row["raw_ref"],
            fetched_at=fetched_at,
            collector="sample-data",
            collector_version="0.1.0",
            content_hash=content_hash,
            tos_compliant=True,
        )
        artifact = Artifact(
            id=f"sample-artifact-{content_hash[:16]}",
            source=source,
            provenance=[provenance],
            content_type="text",
            raw_ref=row["raw_ref"],
            content_hash=content_hash,
            fetched_at=fetched_at,
            text=row["text"],
            metadata={
                "sample": True,
                "entities": row["entities"],
                "geoparsed_places": [row["location_name"]],
            },
        )
        sighting = Sighting(
            id=f"sample-sighting-{content_hash[:16]}",
            artifact_ids=[artifact.id],
            timestamp=fetched_at,
            lat=row["lat"],
            lon=row["lon"],
            location_name=row["location_name"],
            entities=row["entities"],
            description=row["text"],
            confidence=row["confidence"],
            confidence_level=ConfidenceLevel.MEDIUM,
            verification_status=row["status"],
            metadata={"sample": True},
        )
        records.append((artifact, sighting))

    return records
