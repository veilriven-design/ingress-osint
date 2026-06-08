from __future__ import annotations

from typer.testing import CliRunner

from ingress.cli import app


runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "ingress 0.1.0" in result.output


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
