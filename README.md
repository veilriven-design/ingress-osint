# Ingress

**High-integrity open-source platform for military OSINT — analyzing information as it enters the open (public) domains.**

Ingress is a "perfect suite" workbench and automation platform specialized in the *ingress moment*: the first or early public appearance of signals about military forces, equipment, movements, strikes, claims, and effects.

It is designed for analysts, researchers, journalists, and authorized defense teams who need rigorous, reviewable, low-noise tools instead of 20 browser tabs and manual spreadsheets.

> **Status**: Alpha / active development. The `demo` experience is already excellent and representative of the intended quality bar. Real collectors (RSS, Telegram, targeted country ingest) and the full pipeline are working. The comprehensive installer makes deployment trivial on Linux, macOS, and WSL.

## Core Principles

- **Simple, delightful UX hiding extreme care** (inspired by netvis TUI excellence and selconfine "just confine my thing" philosophy).
- **Always reviewable & auditable**. Every artifact, sighting, and fused event carries full provenance, timestamps, hashes, source credibility, and confidence.
- **Data-driven / observation-driven**. Real open signals (social, video, transponders, satellite, official releases) drive everything.
- **Safety & minimality by default**. Targeted collection, capability-scoped collectors, sandboxes for untrusted media, air-gap friendly.
- **Provenance & verifiability first-class** (generalized Oryx visual-confirmation rigor).
- **Legal/ethical hygiene prominent** and per-source. API-first where possible. Strong disclaimers everywhere. Users are responsible for compliance.
- **Local-first / offline capable** (Docker Compose + optional local LLMs via Ollama).

It is **not** a general cyber OSINT toolkit, a bulk scraper, or a replacement for analyst judgment.

## Quick Start (Demo — Zero Dependencies Beyond Python + rich)

**Requires Python 3.10+** (the project declares `requires-python = ">=3.10"`).

Verify first:
```bash
python3 --version   # must be 3.10 or newer. If not, use python3.10 / python3.11 / python3.12 explicitly.
```

```bash
cd ingress
python3 -m pip install -e ".[demo]"
ingress demo
# or for a short automated run
ingress demo --run-seconds 25
```

On systems where `python3` is ancient (e.g. RHEL/AlmaLinux/Rocky 8 family where `python3` = 3.6), use the newer interpreter explicitly:
```bash
python3.11 -m ensurepip --upgrade --user
python3.11 -m pip install -e ".[demo]"
```

## Real Ingest (PR2+)

Install with storage support:
```bash
python3 -m pip install -e ".[storage]"          # or .[full]
# Use python3.11 / python3.12 etc. if `python3` is < 3.10 on your system.
```

SQLite (easiest, no docker):
```bash
ingress ingest rss https://www.defensenews.com/arc/outboundfeeds/rss/ --db-url sqlite:///./data/ingress.db
# or set env
INGRESS_DB_URL=sqlite:///./data/ingress.db ingress ingest rss https://feeds.feedburner.com/DefenseOne
```

### Targeted Country Ingest (real public sources only)

New focused collection using real, publicly known open sources for specific countries.

```bash
# Any combination
ingress ingest target --iran --russia --china --db-url sqlite:///./data/ingress.db

# Or individually
ingress ingest target --russia
```

This uses real public RSS feeds (e.g. Tasnim, Fars, Russian MoD, PLA Daily, Global Times, Oryx) and Telegram channels (e.g. Rybar, official accounts), filtered by deep military keywords. All data is strictly from documented public open sources.

Programmatic access is also available after installing the package:
```python
from ingress import target_iran, target_russia, target_china, target_multiple
arts = target_russia(limit=20, db_url="sqlite:///./data/ingress.db")
```

## Media Workbench (PR3)

```bash
python3 -m pip install -e ".[media]"   # or .[full]
# (use python3.11+ if needed)
ingress analyze /path/to/photo.jpg
ingress analyze https://example.com/strike.mp4 --store --db-url sqlite:///./data/ingress.db
```

Requires (optional but recommended):
- `exiftool` (system package) — the installer now attempts to set this up automatically on supported platforms (EPEL on RHEL-family, etc.)
- `ffmpeg` (for video) — the installer attempts to enable RPM Fusion (free+nonfree) and install on el8 when you run `bash install.sh`
- The media extra above for perceptual hashing.

The analyze command extracts EXIF, perceptual hashes, basic military entity hints, GPS, and can persist a full Artifact with provenance.

## Telegram Collector (PR4)

```bash
python3 -m pip install -e ".[full]"
# (use python3.11+ if `python3 --version` reports older than 3.10)

TELEGRAM_API_ID=123456 TELEGRAM_API_HASH=yourhash \
ingress ingest telegram oryxspioenkop,importantosint --keywords "T-72,convoy,strike" --limit 100 --db-url sqlite:///./data/ingress.db
```

- Only **public** channels.
- Get credentials at https://my.telegram.org (first run creates a session file).
- Respects rate limits and produces full provenance (channel + message_id).
- See `ingress ingest telegram --help` for details.

**Security note**: Never commit API credentials. Use environment variables or a secrets manager.

## Geospatial + "New in Open" (PR5)

```bash
ingress delta --since 24h
ingress export sightings.geojson
```

- Basic geoparsing (geotext + military location booster)
- Sightings table (lat/lon + confidence + linked artifacts)
- Delta / "new in open" detection
- GeoJSON export for mapping tools (QGIS, Kepler, etc.)

Uses the PostGIS setup from docker-compose for production-like geo queries.

## API Skeleton (PR6+)

```bash
python3 -m pip install -e ".[api]"
# (use python3.11+ if needed)
uvicorn src.ingress.api:app --reload
```

Then visit http://localhost:8000/docs for the OpenAPI UI.

Currently exposes /artifacts, /sightings, and a placeholder /ingest.

Postgres / PostGIS (recommended for scale + future geo):

```bash
docker compose up -d db
# run migrations
INGRESS_DB_URL=postgresql://ingress:ingress@localhost:5432/ingress alembic upgrade head
# ingest
INGRESS_DB_URL=postgresql://ingress:ingress@localhost:5432/ingress ingress ingest rss <url>
```

## Simple Comprehensive Installer (all systems, including yours)

```bash
# Clone or download, then:
bash install.sh

# Or one-liner (after first push):
curl -fsSL https://raw.githubusercontent.com/veilriven-design/ingress-osint/main/install.sh | bash
```

- Fully supports your Linux environment (python3.11, apt/dnf/pacman).
- Also macOS (brew) and Windows (WSL recommended).
- Automatically installs system deps (including best-effort for exiftool + ffmpeg via EPEL/RPM Fusion on RHEL 8 family), creates isolated venv, installs with `[full]` extras, sets up SQLite DB, adds `ingress` to PATH.
- Run `ingress watch` immediately after for real-data TUI.
- See `install.sh` for --dev mode and uninstall.

This makes Ingress trivial to deploy anywhere while being serious OSINT tooling.

Helpers:

```bash
ingress db init
```

All new artifacts carry full `ProvenanceEntry` chains (source, fetch time, hash, collector, ToS flag). Dedup is performed on content hash.

Press `q` or Ctrl-C to exit. The demo shows a live-updating rich TUI with:

- Recent open-domain signals (Telegram, RSS, ADS-B, Sentinel-style, user video, etc.)
- Source activity, mentioned entities, confidence bars, verification status
- Realistic multi-source corroboration examples
- Prominent legal/ethical framing

This is the quality bar for every interface Ingress will ship.

## Architecture (High Level)

See `docs/ARCHITECTURE.md` (in progress) and the approved implementation plan in the project session notes.

Key ideas:
- Pluggable collectors (RSS with country targeting support, Telegram public channels, X, ADS-B/AIS, Sentinel, user media workbench, archives...).
- Strong Pydantic models with `ProvenanceEntry` chains on every artifact.
- Async enrichment (NER, geoparsing, perceptual hashing, local vision models, equipment ontology).
- Fusion engine for "new in open", clustering, corroboration scoring.
- TUI (Rich/Textual) + Web dashboard (MapLibre + timelines + cases) + FastAPI.
- Postgres + PostGIS as the heart.
- Local LLMs (Ollama) strongly preferred for extraction/summarization/vision with raw evidence always shown.

## Current Milestone (PR7 complete - more than a demo)

- `ingress watch` / `ingress demo --real` : Live TUI pulling **real data** from your DB (artifacts, sightings, geoparsed places). No more pure canned demo.
- `ingress case create --name foo ; ingress case add --name foo --artifact <id> ; ingress case note ...` : Basic case management (collections + notes).
- Richer experience: sources, entities, geo hints visible in live view.
- Comprehensive installer: `./install.sh` (or curl | bash). Works on Linux (your system), macOS, Windows (WSL). Installs system deps (with media tool support), venv, full extras, initial DB.
- All previous collectors, storage, media, geo, API skeleton included.
- New: Country-targeted ingest (`ingress ingest target`) using only real public open sources for Iran, Russia, China (extensible).

See `ingress --help`, `install.sh --help` (in script), and the installer section below.

- [x] Project bootstrap + beautiful `ingress demo` TUI
- [x] Core models with provenance
- [x] Real RSS collector + storage (sqlite + Postgres/PostGIS via psycopg)
- [x] `ingress ingest rss <url>`
- [x] `ingress analyze <file|url>` (exiftool, perceptual hash, video info, basic entities, GPS, optional storage)
- [x] `ingress db init`, docker-compose (postgis), alembic
- [x] Dual MIT/Apache-2.0 licensing + strong ethics notices
- [x] Comprehensive installer with media tool support on RHEL-family
- [x] Targeted country ingest with real public sources (Iran/Russia/China)
- Next: Stronger fusion, more collectors, local LLM integration, etc. (see plan)

## Important Legal & Ethical Notice

**Ingress is provided for legitimate open-source research, academic study, journalism, and authorized defense/national security analysis only.**

- You are responsible for complying with the laws of your jurisdiction and the Terms of Service of every platform you access via collectors or manually.
- Targeted, API-first collection is the design goal. Indiscriminate bulk scraping may be illegal and/or against ToS.
- The presence of military OSINT capabilities does not authorize surveillance of private individuals or any activity that would be unlawful if performed manually.
- Always attribute sources. Never present model output or fused results as ground truth without verification.

The project includes prominent banners in the TUI, CLI, and README. These are not decorative.

## Roadmap (High Level — See Plan for Details)

Phase 0/1 (current): Foundations + demo + RSS + Telegram public + media workbench + basic geo + "new in open" + targeted ingest + comprehensive installer.

Phase 2: Fusion/corroboration, X collector, local LLM integration, alerting, cases, air-gap bundles.

Phase 3+: Advanced EO, full web UI, plugin ecosystem, structured loss DB mode (Oryx-like), collaboration.

## Contributing

We welcome high-quality, focused contributions that increase capability while preserving reviewability, safety, and legal hygiene.

See `CONTRIBUTING.md` (to be added) and the collector contract / manifest design in the plan.

Before contributing a new collector, please read the ethics and ToS sections.

## Name & License

- Project name: **Ingress** (short for "military information ingress into open domains").
- License: **MIT OR Apache-2.0** (dual, matching the style and precedent of the author's selconfine and l2 projects).

See `LICENSE`, `LICENSE-MIT`, and `LICENSE-APACHE` for the full texts plus the additional use notice.

## Related & Inspiration

- Oryx (oryxspioenkop) visual confirmation methodology
- Bellingcat tradecraft + toolkits (Telepathy, etc.)
- ADS-B Exchange, Sentinel Hub / Copernicus, public AIS communities
- OSINT Framework, ACLED, existing open Telegram monitors
- User's own prior work: netvis (TUI), selconfine (safety + audit model), l2 (high-assurance isolation)

## Acknowledgments

Built with care in the spirit of high-integrity open tools. Credit to all the open collectors, analysts, and researchers who have shown what rigorous public military OSINT looks like.

---

**Ingress is alpha software.** Expect rapid iteration. The demo is the best way to understand the intended experience today.

For the detailed design, PR breakdown, risks, and open decisions, refer to the session plan document.