from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ingress.api import app
from ingress.cli import app as cli_app
from ingress.collectors.network import NetworkTelemetryCollector, split_endpoint
from ingress.storage import ensure_schema, get_recent_artifacts, insert_artifact


runner = CliRunner()


def test_split_endpoint_accepts_urls_hostports_and_ipv6() -> None:
    assert split_endpoint("https://api.chinamil.com.cn:443/path") == ("api.chinamil.com.cn", 443)
    assert split_endpoint("updates.mil.ru:53") == ("updates.mil.ru", 53)
    assert split_endpoint("[2001:4860:4860::8888]:443") == ("2001:4860:4860::8888", 443)


def test_network_collector_builds_targeted_provenanced_artifact() -> None:
    collector = NetworkTelemetryCollector(targets=["china"])
    artifacts = collector.collect_from_records([
        {
            "timestamp": "2026-06-07T18:00:00Z",
            "protocol": "tcp",
            "remote_domain": "api.chinamil.com.cn",
            "remote_port": 443,
            "process": "browser",
            "state": "established",
        },
        {
            "timestamp": "2026-06-07T18:00:01Z",
            "protocol": "tcp",
            "remote_host": "127.0.0.1",
            "remote_port": 8000,
        },
    ])

    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.source.source_type == "network_telemetry"
    assert artifact.content_type == "network_telemetry"
    assert artifact.raw_ref == "network://api.chinamil.com.cn:443"
    assert artifact.provenance[0].collector == "network-telemetry-collector"
    assert artifact.metadata["target_country"] == "china"
    assert "domain_suffix:chinamil.com.cn" in artifact.metadata["matched_network_indicators"]
    assert "no packet content captured" in (artifact.text or "")


def test_network_collector_imports_jsonl_and_filters_focus(tmp_path) -> None:
    telemetry = tmp_path / "network.jsonl"
    telemetry.write_text(
        "\n".join([
            json.dumps({
                "timestamp": datetime(2026, 6, 7, tzinfo=timezone.utc).isoformat(),
                "remote_domain": "updates.mil.ru",
                "remote_port": 443,
                "protocol": "tcp",
            }),
            json.dumps({
                "timestamp": datetime(2026, 6, 7, tzinfo=timezone.utc).isoformat(),
                "remote_domain": "api.chinamil.com.cn",
                "remote_port": 443,
                "protocol": "tcp",
            }),
        ])
        + "\n",
        encoding="utf-8",
    )

    collector = NetworkTelemetryCollector(targets=["russia"])
    artifacts = collector.collect_from_jsonl(telemetry)

    assert len(artifacts) == 1
    assert artifacts[0].metadata["target_country"] == "russia"
    assert artifacts[0].metadata["remote_domain"] == "updates.mil.ru"


def test_network_monitor_cli_imports_jsonl_into_storage(tmp_path) -> None:
    telemetry = tmp_path / "network.jsonl"
    telemetry.write_text(
        json.dumps({
            "timestamp": "2026-06-07T18:00:00Z",
            "remote_domain": "api.chinamil.com.cn",
            "remote_port": 443,
            "protocol": "tcp",
            "process": "browser",
        })
        + "\n",
        encoding="utf-8",
    )
    database_url = f"sqlite:///{tmp_path / 'network.db'}"

    result = runner.invoke(
        cli_app,
        ["monitor", "network", "--input", str(telemetry), "--china", "--db-url", database_url],
    )

    assert result.exit_code == 0, result.output
    assert "Network monitor" in result.output
    assert "Stored 1 new network telemetry artifact" in result.output
    rows = get_recent_artifacts(10, database_url)
    assert rows[0]["source_type"] == "network_telemetry"
    assert "api.chinamil.com.cn" in rows[0]["text"]


def test_network_api_returns_network_observations(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'api-network.db'}"
    ensure_schema(database_url)
    artifact = NetworkTelemetryCollector(targets=["iran"]).collect_from_records([
        {
            "timestamp": "2026-06-07T18:00:00Z",
            "remote_domain": "www.tasnimnews.com",
            "remote_port": 443,
            "protocol": "tcp",
            "process": "curl",
        }
    ])[0]
    insert_artifact(artifact, database_url)

    client = TestClient(app)
    response = client.get("/api/network", params={"target": "iran", "db_url": database_url})

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["observations"] == 1
    assert payload["observations"][0]["network"]["remote_domain"] == "www.tasnimnews.com"
    assert payload["observations"][0]["country_code"] == "IR"


def test_network_api_is_not_starved_by_unfocused_telemetry(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'api-network-noise.db'}"
    ensure_schema(database_url)
    focused = NetworkTelemetryCollector(targets=["china"]).collect_from_records([
        {
            "timestamp": "2026-06-07T18:00:00Z",
            "remote_domain": "api.chinamil.com.cn",
            "remote_port": 443,
            "protocol": "tcp",
            "process": "browser",
        }
    ])[0]
    insert_artifact(focused, database_url)
    noise_records = [
        {
            "timestamp": f"2026-06-07T18:01:{index:02d}Z",
            "remote_domain": f"example-{index}.org",
            "remote_port": 443,
            "protocol": "tcp",
            "process": "browser",
        }
        for index in range(20)
    ]
    for artifact in NetworkTelemetryCollector(
        targets=["china"],
        include_unfocused=True,
    ).collect_from_records(noise_records):
        insert_artifact(artifact, database_url)
    client = TestClient(app)

    response = client.get(
        "/api/network",
        params={"target": "china", "limit": 1, "db_url": database_url},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["observations"] == 1
    assert payload["observations"][0]["network"]["remote_domain"] == "api.chinamil.com.cn"
    assert payload["observations"][0]["country_code"] == "CN"


def test_network_sample_endpoint_populates_network_dashboard(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'network-sample.db'}"
    client = TestClient(app)

    seeded = client.post(
        "/api/network/sample",
        params={"target": "china", "db_url": database_url},
    )
    response = client.get("/api/network", params={"target": "china", "db_url": database_url})

    assert seeded.status_code == 200
    assert seeded.json()["parsed_artifacts"] == 1
    assert seeded.json()["inserted_artifacts"] == 1
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["observations"] == 1
    assert payload["observations"][0]["network"]["ja3"] == "e7d705a3286e19ea42f587b344ee6865"
    assert payload["observations"][0]["network"]["telemetry_source"] == "web-console-sample"
    assert payload["observations"][0]["network"]["demo"] is True
    assert payload["commands"]["monitor_network"].startswith("ingress monitor network --china")


def test_network_live_endpoint_defaults_to_focused_target(monkeypatch) -> None:
    from ingress.collectors import network as network_module

    seen: dict[str, object] = {}

    def fake_collect_local_snapshot(
        self: NetworkTelemetryCollector,
        limit: int | None = None,
    ) -> list[object]:
        seen["include_unfocused"] = self.include_unfocused
        return self.collect_from_records(
            [
                {
                    "timestamp": "2026-06-07T18:00:00Z",
                    "remote_domain": "api.chinamil.com.cn",
                    "remote_port": 443,
                    "protocol": "tcp",
                    "process": "browser",
                },
                {
                    "timestamp": "2026-06-07T18:00:01Z",
                    "remote_domain": "example.org",
                    "remote_port": 443,
                    "protocol": "tcp",
                    "process": "browser",
                },
            ],
            limit=limit,
        )

    monkeypatch.setattr(
        network_module.NetworkTelemetryCollector,
        "collect_local_snapshot",
        fake_collect_local_snapshot,
    )
    client = TestClient(app)

    response = client.get("/api/network/live", params={"target": "china"})

    assert response.status_code == 200
    payload = response.json()
    assert seen["include_unfocused"] is False
    assert payload["mode"] == "live-local"
    assert payload["summary"]["focused_only"] is True
    assert payload["summary"]["observations"] == 1
    assert payload["summary"]["domains"] == [["api.chinamil.com.cn", 1]]
    assert payload["observations"][0]["target"] == "china"
    assert payload["observations"][0]["network"]["remote_domain"] == "api.chinamil.com.cn"


def test_network_collector_accepts_richer_flow_metadata_and_exposes_enrich() -> None:
    collector = NetworkTelemetryCollector(targets=["russia"])
    arts = collector.collect_from_records([
        {
            "timestamp": "2026-06-07T18:05:00Z",
            "protocol": "tcp",
            "remote_domain": "updates.mil.ru",
            "remote_port": 443,
            "sni": "updates.mil.ru",
            "ja3": "a0e9a3e3e3e3e3e3e3e3e3e3e3e3e3e3",
            "bytes_sent": 4200,
            "duration_ms": 890,
            "dns_query": "mil.ru",
        }
    ])
    assert len(arts) == 1
    a = arts[0]
    assert a.metadata.get("target_country") == "russia"
    enrich = a.metadata.get("enriched") or {}
    assert enrich.get("ja3") == "a0e9a3e3e3e3e3e3e3e3e3e3e3e3e3e3"
    assert enrich.get("bytes_sent") == 4200
    assert "ja3" in (a.text or "")
    assert "enriched from flow/packet metadata" in (a.text or "")
    # ja3 promoted for convenience
    assert a.metadata.get("ja3") == "a0e9a3e3e3e3e3e3e3e3e3e3e3e3e3e3"


def test_network_collector_strips_sensitive_payload_and_creds() -> None:
    collector = NetworkTelemetryCollector(targets=["china"], include_unfocused=True)
    arts = collector.collect_from_records([
        {
            "timestamp": "2026-06-07T18:06:00Z",
            "remote_domain": "example.cn",
            "remote_port": 443,
            "protocol": "tcp",
            "payload": b"SECRETPAYLOAD\x00" * 10,  # would be str in real jsonl
            "credential": "AKIAFAKE",
            "http_host": "example.cn",
        }
    ])
    # The record should still produce an artifact (host is public), but sensitive stripped
    assert len(arts) == 1
    # diagnostics should mention the stripped keys
    diags = " ".join(collector.diagnostics)
    assert "sensitive key stripped" in diags
    assert "payload" in diags or "credential" in diags
    # ensure nothing sensitive leaked into the stored artifact text or raw metadata
    meta = arts[0].metadata or {}
    assert "payload" not in str(meta)
    assert "credential" not in str(meta)
    assert "SECRETPAYLOAD" not in (arts[0].text or "")
