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


def test_target_multiple_collects_each_country_with_independent_tags(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run_target_collectors(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs["target_countries"])
        return []

    monkeypatch.setattr(targeting, "_run_target_collectors", fake_run_target_collectors)

    result = targeting.target_multiple(["iran", "china", "iran"], limit=2, db_url="sqlite:///:memory:")

    assert result == []
    assert calls == [["iran"], ["china"]]


def test_current_target_persistence_is_validated(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(targeting, "_TARGET_STATE", tmp_path / "current_target.json")
    monkeypatch.setattr(targeting, "_FALLBACK_TARGET_STATE", tmp_path / "fallback_current_target.json")

    targeting.set_current_target(["iran", "china"])
    assert targeting.get_current_target() == ["iran", "china"]

    (tmp_path / "current_target.json").write_text('{"targets": ["russia", 42, null]}')
    assert targeting.get_current_target() == ["russia"]


def test_current_target_uses_fallback_when_primary_state_is_unwritable(tmp_path, monkeypatch) -> None:
    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("not a directory")
    fallback = tmp_path / "fallback" / "current_target.json"
    monkeypatch.setattr(targeting, "_TARGET_STATE", blocked_parent / "current_target.json")
    monkeypatch.setattr(targeting, "_FALLBACK_TARGET_STATE", fallback)

    assert targeting.set_current_target(["russia"]) is True
    assert fallback.exists()
    assert targeting.get_current_target() == ["russia"]


def test_current_target_reads_newer_fallback_over_stale_primary(tmp_path, monkeypatch) -> None:
    primary = tmp_path / "primary" / "current_target.json"
    fallback = tmp_path / "fallback" / "current_target.json"
    primary.parent.mkdir()
    fallback.parent.mkdir()
    primary.write_text('{"targets": ["iran"]}')
    fallback.write_text('{"targets": ["iran", "russia", "china"]}')
    monkeypatch.setattr(targeting, "_TARGET_STATE", primary)
    monkeypatch.setattr(targeting, "_FALLBACK_TARGET_STATE", fallback)

    assert targeting.get_current_target() == ["iran", "russia", "china"]


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
