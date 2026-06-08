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


def test_web_app_index_is_served() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Ingress Web Console" in response.text
    assert "/assets/app.js" in response.text


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


def test_dashboard_endpoint_filters_and_scores_sqlite_storage(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'dashboard.db'}"
    ensure_schema(database_url)
    source = Source(id="rss-api", name="API RSS", source_type=SourceType.RSS)
    artifact = Artifact(
        source=source,
        provenance=[
            ProvenanceEntry(
                source_id=source.id,
                source_type=SourceType.RSS,
                url_or_id="https://example.com/iran",
                collector="test",
                content_hash="api-dashboard-hash",
            )
        ],
        content_type="text",
        raw_ref="https://example.com/iran",
        content_hash="api-dashboard-hash",
        fetched_at=datetime.now(timezone.utc),
        text="IRGC drone activity reported near the Strait of Hormuz.",
        metadata={"target_country": "iran", "entities": ["IRGC", "drone"]},
    )
    insert_artifact(artifact, database_url)
    client = TestClient(app)

    response = client.get("/api/dashboard", params={"target": "iran", "db_url": database_url})

    assert response.status_code == 200
    payload = response.json()
    assert payload["target"] == "iran"
    assert payload["signals"][0]["country_code"] == "IR"
    assert payload["signals"][0]["criticality_label"] == "high"
    assert "criticality_reason" in payload["signals"][0]


def test_sample_seed_endpoint_populates_dashboard(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'sample-api.db'}"
    client = TestClient(app)

    seeded = client.post("/api/sample", params={"db_url": database_url})
    dashboard = client.get("/api/dashboard", params={"target": "russia", "db_url": database_url})

    assert seeded.status_code == 200
    assert seeded.json()["inserted_artifacts"] == 3
    assert dashboard.status_code == 200
    assert dashboard.json()["summary"]["signals"] == 3


def test_api_ingest_is_explicitly_operator_driven() -> None:
    client = TestClient(app)

    response = client.post("/ingest", json={"source_type": "rss", "url": "https://example.com/feed"})

    assert response.status_code == 200
    assert response.json()["status"] == "not_started"
