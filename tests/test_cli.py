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
