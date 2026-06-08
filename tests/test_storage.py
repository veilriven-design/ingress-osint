from __future__ import annotations

from datetime import datetime, timezone

from ingress.models import (
    Artifact,
    ConfidenceLevel,
    ProvenanceEntry,
    Sighting,
    Source,
    SourceType,
    VerificationStatus,
)
from ingress.storage import ensure_schema, get_recent_artifacts, get_sightings, insert_artifact, insert_sighting


def db_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'ingress.db'}"


def make_artifact(content_hash: str = "hash-1") -> Artifact:
    source = Source(id="rss-test", name="Test RSS", source_type=SourceType.RSS)
    provenance = ProvenanceEntry(
        source_id=source.id,
        source_type=SourceType.RSS,
        url_or_id="https://example.com/a",
        collector="rss-collector",
        content_hash=content_hash,
    )
    return Artifact(
        source=source,
        provenance=[provenance],
        content_type="text",
        raw_ref="https://example.com/a",
        content_hash=content_hash,
        fetched_at=datetime.now(timezone.utc),
        text="T-72 sighting near Pokrovsk",
        metadata={"entities": ["T-72"], "geoparsed_places": ["Pokrovsk"]},
    )


def test_artifact_insert_deduplicates_and_preserves_enum_values(tmp_path) -> None:
    url = db_url(tmp_path)
    ensure_schema(url)

    artifact = make_artifact()
    assert insert_artifact(artifact, url) is True
    assert insert_artifact(artifact, url) is False

    rows = get_recent_artifacts(10, url)
    assert len(rows) == 1
    assert rows[0]["source_type"] == "rss"
    assert rows[0]["source_name"] == "Test RSS"


def test_sighting_round_trips_entities_and_artifact_links(tmp_path) -> None:
    url = db_url(tmp_path)
    ensure_schema(url)
    artifact = make_artifact()
    insert_artifact(artifact, url)

    sighting = Sighting(
        artifact_ids=[artifact.id],
        timestamp=datetime.now(timezone.utc),
        lat=48.0,
        lon=37.8,
        location_name="Pokrovsk",
        entities=["T-72", "Pokrovsk"],
        description="Visual report with location hint",
        confidence=0.7,
        confidence_level=ConfidenceLevel.MEDIUM,
        verification_status=VerificationStatus.ANALYST_REVIEWED,
    )

    assert insert_sighting(sighting, url) is True
    rows = get_sightings(10, url)

    assert len(rows) == 1
    assert rows[0]["entities"] == ["T-72", "Pokrovsk"]
    assert rows[0]["artifact_ids"] == [artifact.id]
