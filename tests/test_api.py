from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from ingress.api import app
from ingress.models import Artifact, ProvenanceEntry, Source, SourceType
from ingress.storage import ensure_schema, insert_artifact


def test_health_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_artifacts_endpoint_reads_sqlite_storage(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'api.db'}"
    ensure_schema(database_url)
    source = Source(id="rss-api", name="API RSS", source_type=SourceType.RSS)
    artifact = Artifact(
        source=source,
        provenance=[
            ProvenanceEntry(
                source_id=source.id,
                source_type=SourceType.RSS,
                url_or_id="https://example.com/api",
                collector="test",
                content_hash="api-hash",
            )
        ],
        content_type="text",
        raw_ref="https://example.com/api",
        content_hash="api-hash",
        fetched_at=datetime.now(timezone.utc),
        text="API visible artifact",
    )
    insert_artifact(artifact, database_url)
    client = TestClient(app)

    response = client.get("/artifacts", params={"db_url": database_url})

    assert response.status_code == 200
    assert response.json()[0]["text"] == "API visible artifact"


def test_api_ingest_is_explicitly_operator_driven() -> None:
    client = TestClient(app)

    response = client.post("/ingest", json={"source_type": "rss", "url": "https://example.com/feed"})

    assert response.status_code == 200
    assert response.json()["status"] == "not_started"
