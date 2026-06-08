# Ingress

High-integrity, local-first tooling for military OSINT signals as they enter public/open domains.

Ingress is for analysts, researchers, journalists, and authorized teams who need a reviewable workbench instead of ad hoc browser tabs and spreadsheets. It prioritizes provenance, bounded collection, explicit operator choices, and clear legal/ethical handling.

Status: alpha, but the core CLI, SQLite storage, RSS ingest, credentialed Telegram ingest, media analysis, case notes, GeoJSON export, and a small FastAPI read surface are implemented and tested.

## What Works Today

- Rich `ingress demo` TUI with synthetic sample signals for first-run orientation.
- `ingress watch` TUI backed by SQLite artifacts, without silently mixing in generated live data.
- RSS/Atom ingest with content-hash deduplication and provenance rows.
- Telegram public-channel ingest through Telethon when `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` are provided.
- Target presets for Iran, Russia, and China that combine public RSS/Telegram source lists and military keyword filters.
- Media analysis for local files or URLs with EXIF, optional perceptual image hash, optional ffprobe video metadata, SHA-256 identity, entity hints, and optional storage.
- SQLite-backed artifacts, provenance, sightings, case notes, delta listing, and GeoJSON export.
- FastAPI skeleton exposing `/health`, `/artifacts`, `/sightings`, and an explicit operator-driven `/ingest` placeholder.
- Ruff, mypy, and pytest coverage for the current core behavior.

Not implemented yet: Postgres/PostGIS migrations, Docker Compose, ADS-B/AIS/Sentinel collectors, X collection, fusion/corroboration scoring, local LLM extraction, and a web dashboard.

## Install For Development

Requires Python 3.10+.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,full]"
.venv/bin/ingress --help
```

For a lighter demo-only install:

```bash
python3 -m pip install -e ".[demo]"
ingress demo --run-seconds 10
```

## CLI Quick Start

Create the local SQLite schema:

```bash
ingress db init --db-url sqlite:///./data/ingress.db
```

Run the demo TUI:

```bash
ingress demo
ingress demo --run-seconds 25
```

Ingest a public RSS feed:

```bash
ingress ingest rss https://www.defensenews.com/arc/outboundfeeds/rss/ \
  --db-url sqlite:///./data/ingress.db
```

Watch stored data:

```bash
ingress watch --db-url sqlite:///./data/ingress.db
```

Use targeted public-source presets:

```bash
ingress ingest target --iran --russia --china --db-url sqlite:///./data/ingress.db
```

Telegram ingest requires credentials from `https://my.telegram.org`:

```bash
TELEGRAM_API_ID=123456 TELEGRAM_API_HASH=yourhash \
ingress ingest telegram oryxspioenkop,importantosint \
  --keywords "T-72,convoy,strike" \
  --limit 100 \
  --db-url sqlite:///./data/ingress.db
```

Analyze media:

```bash
ingress analyze /path/to/photo.jpg --store --db-url sqlite:///./data/ingress.db
ingress analyze https://example.com/strike.mp4 --store --db-url sqlite:///./data/ingress.db
```

Optional system tools improve media analysis:

- `exiftool` for richer EXIF/metadata extraction.
- `ffmpeg` / `ffprobe` for video metadata.

## API

Install with the `api` or `full` extra, then run:

```bash
uvicorn ingress.api:app --reload
```

Useful endpoints:

- `GET /health`
- `GET /artifacts?db_url=sqlite:///./data/ingress.db`
- `GET /sightings?db_url=sqlite:///./data/ingress.db`
- `POST /ingest` returns an explicit handoff to CLI collection so source access remains auditable.

## Verification

```bash
.venv/bin/ruff check .
.venv/bin/mypy src
.venv/bin/python -m pytest
```

## Legal And Ethical Use

Ingress is provided for legitimate open-source research, academic study, journalism, and authorized defense or national-security analysis only.

- Use public data only.
- Respect the laws of your jurisdiction and every source platform's terms.
- Prefer APIs and explicit targeted collection.
- Do not use this tool for unlawful surveillance or indiscriminate scraping.
- Preserve attribution and provenance.
- Treat model output, summaries, and fused claims as leads until verified by an analyst.

## License

Ingress is licensed under either Apache-2.0 or MIT, at your option. See `LICENSE`, `LICENSE-APACHE`, and `LICENSE-MIT`.
