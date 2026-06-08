# Ingress

High-integrity, local-first tooling for military OSINT signals as they enter public/open domains.

Ingress is for analysts, researchers, journalists, and authorized teams who need a reviewable workbench instead of ad hoc browser tabs and spreadsheets. It prioritizes provenance, bounded collection, explicit operator choices, and clear legal/ethical handling.

Status: alpha, but the core CLI, SQLite storage, RSS ingest, credentialed Telegram ingest, media analysis, case notes, GeoJSON export, FastAPI read surface, local web console, and static GitHub Pages console are implemented and tested.

## What Works Today

- Rich `ingress demo` TUI with synthetic sample signals for first-run orientation.
- `ingress watch` TUI (and `watch --live`) backed by SQLite + automatic append-only JSONL audit files: daily `data/ingress-watch-*.jsonl` for rendered watch observations and timestamped `data/ingress-live-*.jsonl` for live polling sessions. `--live` (no country flags) runs the **comprehensive military scanner** for Iran + Russia + China by default, polling dozens of public sources in real time. The TUI adapts to laptop and widescreen terminals, keeps source/link cells clickable in Rich-capable terminals, color-codes criticality, and writes `criticality_reason`, `criticality_terms`, and `raw_ref` for every logged signal.
- RSS/Atom ingest with content-hash deduplication and provenance rows.
- Telegram public-channel ingest through Telethon when `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` are provided.
- Target presets for Iran, Russia, and China that combine dozens of public RSS feeds, Telegram channels, keyword filters, and curated public web pages (from many domains across the internet).
- Media analysis for local files or URLs with EXIF, optional perceptual image hash, optional ffprobe video metadata, SHA-256 identity, entity hints, and optional storage.
- SQLite-backed artifacts, provenance, sightings, case notes, delta listing, and GeoJSON export.
- `ingress doctor`, `ingress status`, and `ingress ingest sample` for local verification without network access.
- FastAPI web/API surface exposing `/health`, `/artifacts`, `/sightings`, `/api/dashboard`, `/api/sample`, and an explicit operator-driven `/ingest` placeholder.
- Ruff, mypy, and pytest coverage for the current core behavior.

Not implemented yet: Postgres/PostGIS migrations, Docker Compose, ADS-B/AIS/Sentinel collectors, full X collection (stub only; requires paid API), fusion/corroboration scoring, and local LLM extraction.

## What's New (v0.2)
- Dramatically expanded public source lists for Iran, Russia, and China (many more RSS feeds from Defense News sections, Kyiv Independent, RealClearDefense, Tasnim, Mehr, SCMP, China defense blogs, Al Jazeera, ISW, etc.).
- New WebPageCollector for high-signal public pages without reliable RSS (e.g. chinamil.com.cn English, Understanding War, Tasnim home, SCMP PLA topics). Explicitly listed and keyword-filtered.
- `ingress watch --live` : real-time background polling of your chosen public RSS + web sources while the TUI renders live updates (plus DB tailer for external ingests). Signals appear with provenance "live-rss:..." / "live-web:...".
- Adaptive watch display: narrow terminals get terse target/source/signal rows plus a compact color-code legend; wider terminals add confidence, status, key terms, and clickable link columns.
- `ingress ingest web <public-url>` for ad-hoc page snapshots.
- Better geoparsing (expanded military locations + optional geotext), stored in artifact metadata for TUI/entities panels.
- All collection remains bounded, keyword-filtered where appropriate, provenance-preserving, and opt-in. "From everywhere on the internet" means curated high-value public domains, not indiscriminate scrape.

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

Check local runtime health:

```bash
ingress doctor --db-url sqlite:///./data/ingress.db
ingress status --db-url sqlite:///./data/ingress.db
```

Populate deterministic synthetic records for a local smoke run:

```bash
ingress ingest sample --db-url sqlite:///./data/ingress.db
ingress status --db-url sqlite:///./data/ingress.db
```

Run the demo TUI:

```bash
ingress demo
ingress demo --run-seconds 25
```

Run the web application:

```bash
uvicorn ingress.api:app --host 127.0.0.1 --port 8765
open http://127.0.0.1:8765
```

The web console reads the same SQLite store as the CLI, shows target tabs for Comprehensive/Iran/Russia/China, exposes clickable source links, turns observed-term chips into filters, renders criticality colors with recorded reasons, and includes a local sample-data button for smoke testing. Collection remains operator-driven through the CLI commands shown in the app. The Auto toggle refreshes the dashboard every 15 minutes.

## GitHub Pages Preview

The same web bundle is published by GitHub Actions from `src/ingress/web` as a GitHub Pages application. It uses the local API when served by FastAPI and falls back to `assets/dashboard-static.json` when `/api/dashboard` is unavailable, such as on GitHub Pages. The Pages workflow refreshes that JSON snapshot every 15 minutes with the public target collector, then the browser refresh button and Auto toggle reload the latest published snapshot client-side. On Pages, the refresh button reports the last check time and whether a newer scheduled snapshot was available; live collection still happens in GitHub Actions or in the local FastAPI/CLI runtime, not inside the static browser page.

Expected Pages URL after the workflow deploys:

```text
https://veilriven-design.github.io/ingress-osint/
```

The Pages version cannot run collectors, mutate SQLite, or seed local sample data because GitHub Pages has no backend. Use the local FastAPI app above for live SQLite-backed collection and review.

Ingest a public RSS feed:

```bash
ingress ingest rss https://www.defensenews.com/arc/outboundfeeds/rss/ \
  --db-url sqlite:///./data/ingress.db
```

Ingest (or snapshot) a specific public web page for sources without RSS:

```bash
ingress ingest web http://eng.chinamil.com.cn/ --db-url sqlite:///./data/ingress.db
```

Watch stored data (or live comprehensive scanner from the open internet):

```bash
ingress watch --db-url sqlite:///./data/ingress.db
# Default "comprehensive military scanner" for Iran + Russia + China:
# Pulls in real time from 40+ public RSS feeds + key web pages (Defense News,
# Kyiv Independent, Tasnim, SCMP, chinamil, ISW, Jamestown, Breaking Defense, etc.).
# All signals are keyword-filtered for military relevance, stored to SQLite,
# AND appended to an easy-to-analyze daily JSONL file (perfect for analysts: jq, tail -f, pandas, etc.).
ingress watch --live --db-url sqlite:///./data/ingress.db

# Or focus on one:
ingress watch --live --russia --db-url sqlite:///./data/ingress.db
```

Analyst tip: after a live scan session the JSONL + the SQLite DB in `data/` give you everything in easily scriptable formats. Example: `jq 'select(.target=="russia") | .text' data/ingress-live-*.jsonl`

Use targeted public-source presets (now with many more public RSS + web pages from global domains):

```bash
ingress ingest target --iran --russia --china --db-url sqlite:///./data/ingress.db
# Real-time watch while collecting in background:
ingress watch --live --russia --db-url sqlite:///./data/ingress.db
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
ingress analyze /path/to/photo.jpg --show-json
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
- `GET /api/dashboard?target=comprehensive`
- `POST /api/sample`
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
