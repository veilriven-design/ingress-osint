from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from ingress.api import app, export_static_dashboard
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
    assert 'href="assets/styles.css"' in response.text
    assert 'src="assets/app.js"' in response.text
    assert "Network Telemetry Review" in response.text
    assert "Capture local snapshot" in response.text
    assert "Live Network Telemetry" not in response.text


def test_github_pages_static_dashboard_snapshot_is_available() -> None:
    snapshot_path = Path("src/ingress/web/assets/dashboard-static.json")

    payload = json.loads(snapshot_path.read_text())

    assert payload["status"] == "static"
    assert payload["target"] == "comprehensive"
    assert {signal["target"] for signal in payload["signals"]} >= {"iran", "russia", "china"}
    assert all(str(signal["raw_ref"]).startswith("https://") for signal in payload["signals"])
    assert all(signal.get("criticality_reason") for signal in payload["signals"])


def test_static_dashboard_exporter_writes_pages_payload(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'pages-export.db'}"
    ensure_schema(database_url)
    source = Source(id="rss-pages", name="Pages RSS", source_type=SourceType.RSS)
    artifact = Artifact(
        source=source,
        provenance=[
            ProvenanceEntry(
                source_id=source.id,
                source_type=SourceType.RSS,
                url_or_id="https://example.com/china",
                collector="test",
                content_hash="pages-dashboard-hash",
            )
        ],
        content_type="text",
        raw_ref="https://example.com/china",
        content_hash="pages-dashboard-hash",
        fetched_at=datetime.now(timezone.utc),
        text="PLA navy exercise reporting with drone and fleet references.",
        metadata={"target_country": "china", "entities": ["PLA", "navy"]},
    )
    insert_artifact(artifact, database_url)
    output = tmp_path / "dashboard-static.json"

    payload = export_static_dashboard(output, db_url=database_url, fallback_path=None)

    written = json.loads(output.read_text())
    assert payload["status"] == "static"
    assert payload["mode"] == "static"
    assert payload["refresh_interval_minutes"] == 15
    assert written["signals"][0]["country_code"] == "CN"


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


def test_dashboard_endpoint_is_not_starved_by_network_telemetry(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'dashboard-public.db'}"
    ensure_schema(database_url)
    now = datetime.now(timezone.utc)
    public_source = Source(id="rss-public", name="Public RSS", source_type=SourceType.RSS)
    public_artifact = Artifact(
        source=public_source,
        provenance=[
            ProvenanceEntry(
                source_id=public_source.id,
                source_type=SourceType.RSS,
                url_or_id="https://example.com/china-public",
                collector="test",
                content_hash="public-dashboard-hash",
            )
        ],
        content_type="text",
        raw_ref="https://example.com/china-public",
        content_hash="public-dashboard-hash",
        fetched_at=now - timedelta(hours=1),
        text="PLA Navy carrier drills reported near the Taiwan Strait.",
        metadata={"target_country": "china", "entities": ["PLA", "Navy"]},
    )
    insert_artifact(public_artifact, database_url)
    network_source = Source(
        id="network-noise",
        name="Network Noise",
        source_type=SourceType.NETWORK_TELEMETRY,
    )
    for index in range(12):
        network_artifact = Artifact(
            source=network_source,
            provenance=[
                ProvenanceEntry(
                    source_id=network_source.id,
                    source_type=SourceType.NETWORK_TELEMETRY,
                    url_or_id=f"network://198.51.100.{index}:443",
                    collector="test",
                    content_hash=f"network-noise-{index}",
                )
            ],
            content_type="network_telemetry",
            raw_ref=f"network://198.51.100.{index}:443",
            content_hash=f"network-noise-{index}",
            fetched_at=now + timedelta(seconds=index),
            text="Unfocused local network metadata.",
            metadata={"target_countries": [], "remote_host": f"198.51.100.{index}"},
        )
        insert_artifact(network_artifact, database_url)
    client = TestClient(app)

    response = client.get(
        "/api/dashboard",
        params={"target": "china", "limit": 1, "db_url": database_url},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["signals"] == 1
    assert payload["signals"][0]["source_type"] == "rss"
    assert payload["signals"][0]["country_code"] == "CN"
    assert "PLA Navy" in payload["signals"][0]["text"]


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
