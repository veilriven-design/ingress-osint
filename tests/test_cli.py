from __future__ import annotations

from typer.testing import CliRunner

from ingress.cli import (
    _link_text,
    _recent_table_columns,
    apply_criticality,
    app,
    artifact_matches_focus,
    clean_display_text,
    display_target_for_signal,
    watch_terms,
)


runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "ingress 0.2.0" in result.output


def test_db_init_command_creates_sqlite_schema(tmp_path) -> None:
    database = tmp_path / "smoke.db"
    result = runner.invoke(app, ["db", "init", "--db-url", f"sqlite:///{database}"])

    assert result.exit_code == 0
    assert database.exists()
    assert "Schema ensured" in result.output


def test_status_points_to_sample_ingest_when_empty(tmp_path) -> None:
    database = tmp_path / "empty.db"
    result = runner.invoke(app, ["status", "--db-url", f"sqlite:///{database}"])

    assert result.exit_code == 0
    assert "No artifacts yet" in result.output
    assert "ingress ingest sample" in result.output


def test_sample_ingest_populates_status_and_deduplicates(tmp_path) -> None:
    database = tmp_path / "sample.db"
    db_url = f"sqlite:///{database}"

    first = runner.invoke(app, ["ingest", "sample", "--db-url", db_url])
    second = runner.invoke(app, ["ingest", "sample", "--db-url", db_url])
    status = runner.invoke(app, ["status", "--db-url", db_url])

    assert first.exit_code == 0
    assert "Inserted 3 artifacts and 3 sightings" in first.output
    assert second.exit_code == 0
    assert "Inserted 0 artifacts and 0 sightings" in second.output
    assert status.exit_code == 0
    assert "Artifacts:" in status.output
    assert "Sample Defense RSS" in status.output


def test_doctor_reports_runtime_table(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INGRESS_STATE_DIR", str(tmp_path / "state"))
    database = tmp_path / "doctor.db"

    result = runner.invoke(app, ["doctor", "--db-url", f"sqlite:///{database}"])

    assert result.exit_code == 0
    assert "Ingress Doctor" in result.output
    assert "SQLite DB" in result.output


def test_rss_dry_run_accepts_local_feed(tmp_path) -> None:
    feed = tmp_path / "feed.xml"
    feed.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Ingress Test Feed</title>
    <item>
      <title>T-72 convoy reported near Pokrovsk</title>
      <link>https://example.com/report-1</link>
      <description>Public report with military keyword.</description>
      <pubDate>Sun, 07 Jun 2026 18:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["ingest", "rss", str(feed), "--dry-run", "--limit", "1"])

    assert result.exit_code == 0
    assert "Parsed 1 candidate" in result.output
    assert "--dry-run: nothing written" in result.output


def test_analyze_is_non_interactive_by_default(tmp_path) -> None:
    media = tmp_path / "sample.jpg"
    media.write_bytes(b"sample media bytes")
    database = tmp_path / "media.db"

    result = runner.invoke(
        app,
        ["analyze", str(media), "--store", "--db-url", f"sqlite:///{database}"],
    )

    assert result.exit_code == 0
    assert "Media Analysis Summary" in result.output
    assert "Stored as Artifact" in result.output


def test_watch_terms_backfills_old_rss_rows_without_match_metadata() -> None:
    text = clean_display_text("<p>Russian drone hit a depot; Russian air defense systems were reported nearby.</p>")

    terms = watch_terms({}, text, ["russia"])

    assert text == "Russian drone hit a depot; Russian air defense systems were reported nearby."
    assert "russian drone" in terms
    assert "russian air defense systems" in terms


def test_watch_display_columns_adapt_to_terminal_width() -> None:
    narrow = [column[0] for column in _recent_table_columns(80)]
    laptop = [column[0] for column in _recent_table_columns(100)]
    wide = [column[0] for column in _recent_table_columns(140)]

    assert narrow == ["time", "crit", "country", "source", "signal"]
    assert laptop == ["time", "crit", "country", "source", "signal", "conf", "status"]
    assert wide == ["time", "crit", "country", "source", "signal", "key", "conf", "status", "link"]


def test_watch_source_links_are_rich_clickable_text() -> None:
    text = _link_text("source", "https://example.com/report")

    assert text.style.link == "https://example.com/report"
    assert text.style.underline is True


def test_criticality_reason_is_persistable_and_term_based() -> None:
    sig = {
        "text": "Public report: Russian drone strike near air defense site.",
        "entities": ["air defense"],
        "source": "example",
        "status": "unverified",
        "confidence": 0.55,
    }

    apply_criticality(sig)

    assert sig["criticality_color"] == "red"
    assert sig["criticality_label"] == "high"
    assert "drone" in sig["criticality_terms"]
    assert "status=unverified" in sig["criticality_reason"]
    assert "confidence=55%" in sig["criticality_reason"]


def test_unstamped_rows_must_match_current_target_focus() -> None:
    metadata: dict[str, object] = {}
    china_text = "PLA Navy carrier drills continue near the Taiwan Strait."
    iran_text = "IRGC Navy units announced a Strait of Hormuz exercise."

    assert artifact_matches_focus(metadata, china_text, ["china"], source="scmp.com")
    assert not artifact_matches_focus(metadata, china_text, ["iran"], source="scmp.com")
    assert artifact_matches_focus(metadata, iran_text, ["iran"], source="tehrantimes.com")
    assert display_target_for_signal(metadata, iran_text, ["iran"], source="tehrantimes.com") == "iran"


def test_config_keywords_do_not_count_as_observed_target_evidence() -> None:
    metadata = {"target_keywords": ["IRGC", "Strait of Hormuz"]}
    text = "PLA Navy carrier drills continue near the Taiwan Strait."

    assert not artifact_matches_focus(metadata, text, ["iran"], source="scmp.com")
    assert watch_terms(metadata, text, ["iran"]) == []


def test_watch_with_explicit_target_renders_focused_snapshot(tmp_path, monkeypatch) -> None:
    from ingress import targeting

    monkeypatch.setenv("INGRESS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(targeting, "_TARGET_STATE", tmp_path / "state" / "current_target.json")
    monkeypatch.setattr(targeting, "_FALLBACK_TARGET_STATE", tmp_path / "fallback_current_target.json")
    targeting.set_current_target(["iran"])
    database = tmp_path / "watch.db"
    db_url = f"sqlite:///{database}"

    sample = runner.invoke(app, ["ingest", "sample", "--db-url", db_url])
    result = runner.invoke(app, ["watch", "--russia", "--run-seconds", "1", "--db-url", db_url])

    assert sample.exit_code == 0
    assert result.exit_code == 0, result.output
    assert "Russia Military" in result.output
    assert "INGRESS  •  Iran Military" not in result.output
    assert "Targeted watch for Russia" in result.output or "Russia" in result.output
    assert "Sample Defense RSS" in result.output or "Sample" in result.output
    assert "Ingress watch snapshot rendered." in result.output
    assert "Press 'q'" not in result.output


def test_watch_uses_saved_target_when_no_explicit_target_is_given(tmp_path, monkeypatch) -> None:
    from ingress import targeting

    monkeypatch.setenv("INGRESS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(targeting, "_TARGET_STATE", tmp_path / "state" / "current_target.json")
    monkeypatch.setattr(targeting, "_FALLBACK_TARGET_STATE", tmp_path / "fallback_current_target.json")
    database = tmp_path / "watch-saved-target.db"
    db_url = f"sqlite:///{database}"

    assert targeting.set_current_target(["russia"]) is True
    sample = runner.invoke(app, ["ingest", "sample", "--db-url", db_url])
    result = runner.invoke(app, ["watch", "--run-seconds", "1", "--db-url", db_url])

    assert sample.exit_code == 0
    assert result.exit_code == 0, result.output
    assert "INGRESS  •  Russia Military" in result.output
    assert "Targeted watch for Russia; showing stored artifacts." in result.output
    assert "Sample Defense RSS" in result.output


def test_watch_live_without_flags_uses_comprehensive_focus(monkeypatch) -> None:
    import ingress.cli as cli

    captured: dict[str, object] = {}

    def fake_run_watch(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(cli, "run_watch", fake_run_watch)

    result = runner.invoke(app, ["watch", "--live", "--run-seconds", "1"])

    assert result.exit_code == 0, result.output
    assert captured["live"] is True
    assert captured["focus_targets"] == ["iran", "russia", "china"]


def test_empty_watch_renders_target_context_instead_of_dead_wait_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INGRESS_STATE_DIR", str(tmp_path / "state"))
    database = tmp_path / "empty-watch.db"
    db_url = f"sqlite:///{database}"

    result = runner.invoke(app, ["watch", "--russia", "--run-seconds", "1", "--db-url", db_url])

    assert result.exit_code == 0, result.output
    assert "Russia Military" in result.output or "Russia" in result.output
    assert "Watch is active for Russia" in result.output or "No stored artifacts" in result.output or "active for Russia" in result.output
    assert "ingress ingest target --russia" in result.output or "ingest target" in result.output
    assert "waiting for signals..." not in result.output


def test_watch_filters_stored_rows_that_have_other_target_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INGRESS_STATE_DIR", str(tmp_path / "state"))
    database = tmp_path / "watch-filter.db"
    db_url = f"sqlite:///{database}"

    sample = runner.invoke(app, ["ingest", "sample", "--db-url", db_url])
    result = runner.invoke(app, ["watch", "--china", "--run-seconds", "1", "--db-url", db_url])

    assert sample.exit_code == 0
    assert result.exit_code == 0, result.output
    assert "INGRESS  •  China Military" in result.output
    assert "No stored artifacts match current focus: China." in result.output
    assert "Sample Defense RSS" not in result.output
