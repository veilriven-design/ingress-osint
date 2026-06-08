from __future__ import annotations

from datetime import datetime, timezone

from ingress.collectors.telegram import TelegramCollector
from ingress import targeting


def test_target_config_merges_and_deduplicates() -> None:
    config = targeting.get_target_config(["iran", "russia", "iran"])

    assert "rss_feeds" in config
    assert len(config["rss_feeds"]) == len(set(config["rss_feeds"]))
    assert "IRGC" in config["keywords"]
    assert "T-72" in config["keywords"]
    assert "Iranian military" in config["description"]
    assert "Russian military" in config["description"]


def test_current_target_persistence_is_validated(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(targeting, "_TARGET_STATE", tmp_path / "current_target.json")

    targeting.set_current_target(["iran", "china"])
    assert targeting.get_current_target() == ["iran", "china"]

    (tmp_path / "current_target.json").write_text('{"targets": ["russia", 42, null]}')
    assert targeting.get_current_target() == ["russia"]


def test_telegram_collector_builds_provenanced_artifact() -> None:
    collector = TelegramCollector(
        api_id=1,
        api_hash="hash",
        channels=["example"],
        keywords=["t-72"],
    )

    artifact = collector._message_to_artifact(
        "example",
        42,
        "T-72 convoy reported in public channel",
        datetime(2026, 6, 7, tzinfo=timezone.utc),
    )

    assert artifact.source.source_type == "telegram"
    assert artifact.raw_ref == "https://t.me/example/42"
    assert artifact.provenance[0].collector == "telegram-collector"
    assert artifact.content_hash
