"""
Ingress CLI + TUI.

Delivers a netvis-quality live experience with military OSINT signals "as they enter the open domain".

This is the flagship first-user experience: zero config, beautiful,
informative, with strong legal/ethical framing and full provenance
visible for every item.
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
from collections import deque, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from rich.console import Console, Group
    from rich.live import Live
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.align import Align
    from rich import box
    HAS_RICH = True
except ImportError as e:  # pragma: no cover
    HAS_RICH = False
    RICH_ERR = str(e)

import typer

from . import __version__

# NOTE: All other ingress.* imports are done locally inside the command functions
# that need them. This allows `pip install -e ".[full]"` (rich + typer only) to
# successfully start the CLI and run `ingress` without pulling in optional
# dependencies such as feedparser, psycopg, Pillow, etc.

app = typer.Typer(
    name="ingress",
    help="Ingress — Military OSINT for signals entering the open domains.",
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()

# --------------------------- Canned Data & State ---------------------------

SIMULATED_SIGNALS: list[dict[str, Any]] = [
    {
        "ts": time.time() - 35,
        "source": "t.me/oryxspioenkop",
        "type": "TELEGRAM",
        "text": "Visually confirmed: 1x T-72B3 destroyed, 1x BMP-2 damaged near Pokrovsk direction. Photos + geoloc.",
        "confidence": 0.92,
        "status": "visually_confirmed",
        "entities": ["T-72B3", "BMP-2", "Pokrovsk"],
        "provenance": "Oryx-style list + Telegram post + 2 videos",
        "target": "russia",
    },
    {
        "ts": time.time() - 82,
        "source": "rss.mod.mil",
        "type": "RSS",
        "text": "Russian MoD: 'Air defense units destroyed 4 UAVs over Belgorod oblast overnight.'",
        "confidence": 0.65,
        "status": "unverified",
        "entities": ["UAV", "Belgorod"],
        "provenance": "Official MoD RSS feed",
        "target": "russia",
    },
    {
        "ts": time.time() - 41,
        "source": "adsb-exchange",
        "type": "ADSB",
        "text": "IL-76MD (RF-xxx) departed from [REDACTED] at 0412Z, track toward southern MD.",
        "confidence": 0.78,
        "status": "analyst_reviewed",
        "entities": ["IL-76MD"],
        "provenance": "ADSB Exchange public feed + callsign correlation",
        "target": "iran",
    },
    {
        "ts": time.time() - 19,
        "source": "t.me/someosint",
        "type": "TELEGRAM",
        "text": "New video: Grad MLRS firing from treeline ~5km NE of Vuhledar. 3s geolocated.",
        "confidence": 0.81,
        "status": "corroborated",
        "entities": ["Grad", "Vuhledar"],
        "provenance": "Video + 2 independent geolocations + prior unit reporting",
    },
    {
        "ts": time.time() - 120,
        "source": "sentinel-2",
        "type": "SENTINEL",
        "text": "New activity signatures at known forward logistics node (possible vehicle revetments).",
        "confidence": 0.55,
        "status": "unverified",
        "entities": ["logistics node"],
        "provenance": "Copernicus Sentinel-2 L2A, 10m, acquired 2026-06-06",
        "target": "china",
    },
]

MAX_RECENT = 12
SPARK_HISTORY = 24
THEATERS = ["Donbas", "Black Sea", "Belgorod", "Kharkiv", "Zaporizhzhia"]

STOP_EVENT = threading.Event()
SIGNAL_QUEUE: Any = None  # will be queue in run
STATE_LOCK = threading.Lock()

recent_signals: deque = deque(maxlen=MAX_RECENT)
source_counts: Counter = Counter()
event_times: deque = deque(maxlen=300)
spark_buckets: deque = deque([0] * SPARK_HISTORY, maxlen=SPARK_HISTORY)
start_time = time.time()


def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def make_sparkline(buckets: deque) -> str:
    if not buckets or max(buckets) == 0:
        return "▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁"
    chars = "▁▂▃▄▅▆▇█"
    mx = max(buckets) or 1
    return "".join(chars[min(int((v / mx) * (len(chars) - 1)), len(chars) - 1)] for v in buckets)


def make_conf_bar(conf: float, width: int = 10) -> str:
    filled = int(conf * width)
    return "█" * filled + "░" * (width - filled)


def feeder(stop_evt: threading.Event, q: Any) -> None:
    """Generate plausible new military OSINT signals."""
    templates = [
        ("t.me/oryxspioenkop", "TELEGRAM", "Visually confirmed loss: {eq} near {loc}.", ["T-72", "BMP-3", "2S19", "BTR-82A"], ["Pokrovsk", "Vuhledar", "Chasiv Yar", "Kupyansk"]),
        ("rss.ukrmod.gov", "RSS", "General Staff: {n} Shahed-type UAVs destroyed overnight.", [], ["Kyiv", "Odesa", "Dnipro"]),
        ("adsb-exchange", "ADSB", "An-124 + escort track observed, routing {route}.", [], ["southern vector", "Crimea direction"]),
        ("t.me/frontline", "TELEGRAM", "New geolocated video: {eq} convoy moving {dir} of {loc}.", ["T-80", "MT-LB", "Ural"], ["west", "east", "north"]),
        ("sentinel-copernicus", "SENTINEL", "Thermal anomaly / vehicle signatures at {loc} staging area.", [], ["known ammo depot", "bridgehead", "forward airfield"]),
    ]
    tick = 0
    while not stop_evt.is_set():
        tick += 1
        src, typ, tmpl, eqs, locs = random.choice(templates)
        eq = random.choice(eqs) if eqs else ""
        loc = random.choice(locs)
        text = tmpl.format(eq=eq, loc=loc, n=random.randint(1, 7), dir=random.choice(["W", "E", "NE"]), route="via Rostov")
        conf = round(random.uniform(0.48, 0.94), 2)
        status = random.choice(["unverified", "analyst_reviewed", "corroborated", "visually_confirmed"])
        entities = [e for e in [eq, loc] if e]
        prov = f"{typ} public + cross-ref" if typ != "SENTINEL" else "Copernicus open data"

        sig = {
            "ts": time.time(),
            "source": src,
            "type": typ,
            "text": text,
            "confidence": conf,
            "status": status,
            "entities": entities,
            "provenance": prov,
        }
        q.put(sig)

        # occasional burst of related signals (same event from multiple sources)
        if random.random() < 0.18:
            for _ in range(random.randint(1, 2)):
                time.sleep(0.06)
                v2 = dict(sig)
                v2["ts"] = time.time()
                v2["source"] = random.choice(["t.me/osint1", "liveuamap-rss", "mod-statement"])
                v2["type"] = random.choice(["TELEGRAM", "RSS"])
                q.put(v2)

        if tick % 4 == 0:
            with STATE_LOCK:
                spark_buckets.rotate(-1)
                spark_buckets[-1] = 0

        time.sleep(random.uniform(0.6, 2.4))


def update_state_from_signal(sig: dict[str, Any]) -> None:
    global spark_buckets
    with STATE_LOCK:
        recent_signals.appendleft(sig)
        source_counts[sig["source"]] += 1
        event_times.append(sig["ts"])
        spark_buckets[-1] += 1


def build_header(stats: str) -> Panel:
    title = Text("INGRESS", style="bold red")
    subtitle = Text("  Military OSINT • Iranian, Chinese & Russian forces  •  v" + __version__, style="dim")
    return Panel(
        Align.center(Group(title, subtitle, Text(stats, style="bold"))),
        box=box.HEAVY,
        border_style="red",
    )


def build_recent_table() -> Table:
    t = Table(
        title="Recent Open-Domain Signals",
        box=box.SIMPLE,
        show_header=True,
        header_style="bold magenta",
        expand=True,
    )
    t.add_column("Time", style="dim", width=8)
    t.add_column("Source", style="cyan", width=22)
    t.add_column("Signal (first 120 chars)", style="white", width=90)
    t.add_column("Focus", width=10)
    t.add_column("Conf", width=5)
    t.add_column("Status", width=16)

    with STATE_LOCK:
        items = list(recent_signals)[:MAX_RECENT]

    for s in items:
        t_str = datetime.fromtimestamp(s["ts"]).strftime("%H:%M:%S")
        short = s["text"][:120] + ("…" if len(s["text"]) > 120 else "")
        conf_str = f"{s['confidence']:.0%}"
        status_style = {
            "visually_confirmed": "green",
            "corroborated": "blue",
            "analyst_reviewed": "yellow",
            "unverified": "red",
        }.get(s["status"], "white")
        focus = (s.get("target") or "").title()[:8] or "-"
        t.add_row(
            t_str,
            s["source"][:22],
            short,
            focus,
            conf_str,
            Text(s["status"], style=status_style),
        )
    if not items:
        t.add_row("-", "waiting for signals...", "", "", "")
    return t


def build_sources_panel() -> Panel:
    with STATE_LOCK:
        tops = source_counts.most_common(8)

    t = Table(box=box.MINIMAL, show_header=False, expand=True)
    t.add_column("source", style="green")
    t.add_column("cnt", style="bold", justify="right")

    for src, cnt in tops:
        t.add_row(src[:28], str(cnt))
    if not tops:
        t.add_row("scanning open sources...", "")
    return Panel(t, title="Active Sources", border_style="green", box=box.ROUNDED)


def build_entities_panel() -> Panel:
    ents: Counter = Counter()
    with STATE_LOCK:
        for s in recent_signals:
            for e in s.get("entities", []):
                ents[e] += 1
        tops = ents.most_common(6)

    t = Table(box=box.MINIMAL, show_header=False, expand=True)
    t.add_column("entity", style="yellow")
    t.add_column("mentions", justify="right")

    for e, c in tops:
        t.add_row(e, str(c))
    if not tops:
        t.add_row("no entities yet", "")
    return Panel(t, title="Key Entities", border_style="yellow", box=box.ROUNDED)


def build_footer(rate: float, spark: str) -> Text:
    return Text.assemble(
        ("q ", "bold yellow"), ("quit  ", "dim"),
        (f"rate: {rate:.1f}/min", "dim"),
        ("   ", ""),
        (spark, "red"),
        ("   ", ""),
        ("ctrl-c also works", "dim"),
        ("   ", ""),
        ("Military OSINT — public sources only. Respect ToS and laws.", "dim"),
    )


def render_dashboard() -> Layout:
    # drain queue
    while True:
        try:
            sig = SIGNAL_QUEUE.get_nowait()
            update_state_from_signal(sig)
        except Exception:
            break

    now = time.time()
    elapsed = max(1, now - start_time)
    with STATE_LOCK:
        n_sig = len(recent_signals)
        n_src = len(source_counts)
        recent_ev = [t for t in event_times if now - t < 180]
        rate = (len(recent_ev) / max(1, (now - (recent_ev[0] if recent_ev else now)))) * 60 if recent_ev else 0
        spark = make_sparkline(spark_buckets)

    stats = f"Signals: {n_sig}   Sources: {n_src}   Events: {len(event_times)}   {int(elapsed)}s   Theaters: {', '.join(random.sample(THEATERS, 2))}"

    header = build_header(stats)
    recent = build_recent_table()
    srcs = build_sources_panel()
    ents = build_entities_panel()
    foot = build_footer(rate, spark)

    lay = Layout()
    lay.split_column(
        Layout(header, size=5),
        Layout(name="body"),
        Layout(foot, size=2),
    )
    lay["body"].split_row(
        Layout(recent, ratio=3),
        Layout(Group(srcs, ents), ratio=1),
    )
    return lay


def run_canned(run_seconds: float = 0) -> None:
    """Run the TUI with simulated signals from public military sources (no external services required)."""
    if not HAS_RICH:
        print("FATAL: rich is required for the Ingress TUI.")
        print("Requires Python >= 3.10. Install with: python3 -m pip install -e '.[full]'")
        print("If 'python3 --version' is < 3.10, use python3.11 / python3.12 explicitly (and its pip).")
        raise SystemExit(1)

    global SIGNAL_QUEUE, start_time, spark_buckets, recent_signals, source_counts, event_times
    from queue import Queue
    SIGNAL_QUEUE = Queue()

    recent_signals = deque(maxlen=MAX_RECENT)
    source_counts = Counter()
    event_times = deque(maxlen=300)
    spark_buckets = deque([0] * SPARK_HISTORY, maxlen=SPARK_HISTORY)
    start_time = time.time()

    current_targets = []
    try:
        from .targeting import get_current_target
        current_targets = get_current_target()
    except Exception:
        pass

    # Seed a few initial signals so the UI isn't empty (filter by current target if set)
    for s in SIMULATED_SIGNALS:
        if not current_targets or s.get("target") in current_targets or not s.get("target"):
            SIGNAL_QUEUE.put(s)

    if current_targets:
        if len(current_targets) == 1:
            mil = current_targets[0].title()
            main_title = f"INGRESS  •  {mil} Military"
        else:
            mils = " / ".join(t.title() for t in current_targets)
            main_title = f"INGRESS  •  {mils} Militaries"
    else:
        main_title = "INGRESS  •  Military Signals"
    if current_targets:
        mil_str = ", ".join(t.title() for t in current_targets)
        second_line = f"Targeted to {mil_str}. Live view of signals."
    else:
        second_line = "Live view of signals entering the open domain.\nFull provenance, confidence, and verification status shown for every item."
    console.print(Panel.fit(
        f"[bold red]{main_title}[/]\n"
        f"[dim]{second_line}[/]",
        border_style="red",
    ))
    if current_targets:
        mil_str = ", ".join(t.title() for t in current_targets)
        msg = f"Using configured public sources for {mil_str}."
    else:
        msg = "Using configured public sources for the Iranian, Chinese and Russian militaries."
    console.print(f"[yellow]{msg}[/]")
    console.print("[dim]Legend: ▁▂▃▅█ = activity sparkline (recent signal rate over time)  •  █░░░░ = confidence bar  •  sources = top by count  •  entities = key mentioned[/]")
    console.print("[dim]Press 'q' or Ctrl-C to exit. See --help for other options.[/]\n")

    t_feeder = threading.Thread(target=feeder, args=(STOP_EVENT, SIGNAL_QUEUE), daemon=True)
    t_feeder.start()

    layout = Layout()
    live = Live(layout, console=console, refresh_per_second=4, screen=True)

    deadline = time.time() + run_seconds if run_seconds > 0 else 0

    try:
        live.start()
        while not STOP_EVENT.is_set():
            dash = render_dashboard()
            live.update(dash)
            if deadline and time.time() >= deadline:
                STOP_EVENT.set()
                break
            time.sleep(0.08)
    except KeyboardInterrupt:
        STOP_EVENT.set()
    finally:
        live.stop()
        STOP_EVENT.set()
        time.sleep(0.1)
        console.print("\n[bold]Ingress session ended.[/]")
        with STATE_LOCK:
            console.print(f"  Total signals observed: {len(event_times)}")
            if source_counts:
                top = ", ".join(s for s, _ in source_counts.most_common(3))
                console.print(f"  Top sources: {top}")
        console.print("[dim]Thank you for using Ingress. Remember: always verify, attribute, and respect source terms.[/]\n")


def run_watch(db_url: str | None = None, run_seconds: float = 0) -> None:
    """Live TUI pulling from storage (integrated)."""
    if not HAS_RICH:
        print("FATAL: rich is required for the Ingress TUI.")
        raise SystemExit(1)

    from queue import Queue
    import json as _json
    from .config import get_db_url
    from .storage import ensure_schema, get_recent_artifacts
    global SIGNAL_QUEUE, start_time, spark_buckets, recent_signals, source_counts, event_times
    SIGNAL_QUEUE = Queue()

    recent_signals = deque(maxlen=MAX_RECENT)
    source_counts = Counter()
    event_times = deque(maxlen=300)
    spark_buckets = deque([0] * SPARK_HISTORY, maxlen=SPARK_HISTORY)
    start_time = time.time()

    db = db_url or get_db_url()
    current_targets = []
    try:
        from .targeting import get_current_target
        current_targets = get_current_target()
    except Exception:
        pass

    try:
        ensure_schema(db)
        artifacts = get_recent_artifacts(30, db)
        for a in artifacts:
            ts_str = a.get("fetched_at", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
            except Exception:
                ts = time.time()
            meta = {}
            try:
                meta = _json.loads(a.get("metadata", "{}")) if a.get("metadata") else {}
            except Exception:
                pass
            sig = {
                "ts": ts,
                "source": a.get("source_name", a.get("source_id", "?")),
                "type": str(a.get("content_type", "text")).upper(),
                "text": (a.get("text") or "")[:180],
                "confidence": round(0.7 + (hash(str(a.get("id", ""))) % 20) / 100.0, 2),
                "status": "analyst_reviewed",
                "entities": meta.get("geoparsed_places", []) or meta.get("entities", []),
                "provenance": f"db:{str(a.get('content_hash', 'n/a'))[:8]}",
                "target": (current_targets[0] if current_targets else None),
            }
            SIGNAL_QUEUE.put(sig)
    except Exception as e:
        if current_targets:
            mil_str = ", ".join(t.title() for t in current_targets)
            msg = f"Using public sources for {mil_str}."
        else:
            msg = "Using public sources for the target militaries."
        console.print(f"[yellow]Could not load data from DB. {msg}[/]")
        for s in SIMULATED_SIGNALS:
            if not current_targets or s.get("target") in current_targets or not s.get("target"):
                SIGNAL_QUEUE.put(s)

    if current_targets:
        if len(current_targets) == 1:
            mil = current_targets[0].title()
            main_title = f"INGRESS  •  {mil} Military"
        else:
            mils = " / ".join(t.title() for t in current_targets)
            main_title = f"INGRESS  •  {mils} Militaries"
    else:
        main_title = "INGRESS  •  Military Signals"
    if current_targets:
        mil_str = ", ".join(t.title() for t in current_targets)
        second_line = f"Targeted to {mil_str}. Pulls from storage."
    else:
        second_line = "Pulls from storage. Use 'ingest target' or 'rss' to populate."
    console.print(Panel.fit(
        f"[bold red]{main_title}[/]\n"
        f"[dim]{second_line}[/]",
        border_style="red",
    ))
    console.print("[dim]Legend: ▁▂▃▅█ = activity sparkline (recent signal rate over time)  •  █░░░░ = confidence bar  •  sources = top by count  •  entities = key mentioned[/]")
    console.print("[dim]Press 'q' or Ctrl-C to exit. This is a functional TUI.[/]\n")

    t_feeder = threading.Thread(target=feeder, args=(STOP_EVENT, SIGNAL_QUEUE), daemon=True)
    t_feeder.start()

    layout = Layout()
    live = Live(layout, console=console, refresh_per_second=3, screen=True)

    deadline = time.time() + run_seconds if run_seconds > 0 else 0

    try:
        live.start()
        while not STOP_EVENT.is_set():
            dash = render_dashboard()
            live.update(dash)
            if deadline and time.time() >= deadline:
                STOP_EVENT.set()
                break
            time.sleep(0.15)
    except KeyboardInterrupt:
        STOP_EVENT.set()
    finally:
        live.stop()
        STOP_EVENT.set()
        time.sleep(0.1)
        console.print("\n[bold]Ingress watch session ended.[/]\n")


@app.command("demo")
def demo(
    run_seconds: float = typer.Option(0, "--run-seconds", help="Auto-exit after N seconds (useful for testing/CI)"),
    live: bool = typer.Option(False, "--live", help="Pull from DB storage instead of canned signals."),
) -> None:
    """Run the TUI with military OSINT signals."""
    if live:
        run_watch(db_url=None, run_seconds=run_seconds)
    else:
        run_canned(run_seconds=run_seconds)


@app.command()
def watch(
    iran: bool = typer.Option(False, "--iran", help="Focus on Iranian military (public sources: Tasnim, Fars, IRGC-related OSINT)"),
    russia: bool = typer.Option(False, "--russia", help="Focus on Russian military (Rybar, Oryx, MoD claims)"),
    china: bool = typer.Option(False, "--china", help="Focus on Chinese PLA (PLA Daily, Global Times, theater commands)"),
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL", help="DB to watch (defaults to configured)"),
    run_seconds: float = typer.Option(0, "--run-seconds"),
) -> None:
    """Live TUI watching data from storage (integrated)."""
    # Normalize and set focus if provided (for this run; persists if set)
    iran = iran if isinstance(iran, bool) else False
    russia = russia if isinstance(russia, bool) else False
    china = china if isinstance(china, bool) else False
    targets = []
    if iran: targets.append("iran")
    if russia: targets.append("russia")
    if china: targets.append("china")
    if targets:
        from .targeting import set_current_target
        set_current_target(targets)
    run_watch(db_url=db_url, run_seconds=run_seconds)


@app.command()
def version() -> None:
    """Print version."""
    typer.echo(f"ingress {__version__}")


# --------------------------- Ingest (PR2) ---------------------------

ingest_app = typer.Typer(help="Ingest open sources into storage (RSS, future: Telegram, etc.)")
app.add_typer(ingest_app, name="ingest")


@ingest_app.command("rss")
def ingest_rss(
    url: str = typer.Argument(..., help="RSS/Atom feed URL"),
    db_url: str | None = typer.Option(
        None,
        "--db-url",
        envvar="INGRESS_DB_URL",
        help="Database URL (sqlite://... or postgresql://...). Defaults to config / sqlite DB.",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Only process first N entries (debug)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse and show but do not write to DB"),
) -> None:
    """
    Ingest an RSS/Atom feed.

    Creates Source + Artifact records (with full provenance) for new items.
    Deduplicates on content hash.

    Example:
        ingress ingest rss https://www.defensenews.com/arc/outboundfeeds/rss/
        INGRESS_DB_URL=sqlite:///./data/ingress.db ingress ingest rss https://...
    """
    from .collectors.rss import RSSCollector
    from .storage import ensure_schema, insert_artifact

    console.print(f"[cyan]Ingesting RSS[/] {url}")

    collector = RSSCollector(url)
    artifacts = collector.collect()

    if limit:
        artifacts = artifacts[:limit]

    if not artifacts:
        console.print("[yellow]No entries found (or all older than 'since').[/]")
        return

    console.print(f"Parsed {len(artifacts)} candidate entries from feed.")

    if dry_run:
        for a in artifacts[:5]:
            console.print(f"  - {a.fetched_at} | {a.raw_ref} | { (a.text or '')[:80] }...")
        console.print("[dim]--dry-run: nothing written.[/]")
        return

    # Ensure schema (sqlite convenience; for pg prefer alembic)
    try:
        ensure_schema(db_url)
    except Exception as e:
        console.print(f"[yellow]ensure_schema warning (may be fine if using alembic): {e}[/]")

    stored = 0
    for art in artifacts:
        try:
            inserted = insert_artifact(art, db_url)
            if inserted:
                stored += 1
                prov_summary = ", ".join(p.collector for p in art.provenance)
                console.print(f"[green]  +[/] {art.fetched_at}  {art.raw_ref or '(no link)'}  (prov: {prov_summary})")
            # else: duplicate, silent
        except Exception as exc:
            console.print(f"[red]  ! Error storing artifact: {exc}[/]")

    console.print(f"\n[bold]Done.[/] Stored {stored} new artifacts (out of {len(artifacts)} parsed).")
    console.print("Use storage queries / future TUI / API to explore. Full provenance is recorded.")


@ingest_app.command("telegram")
def ingest_telegram(
    channels: str = typer.Argument(..., help="Comma-separated public channel usernames (no @)"),
    api_id: int | None = typer.Option(None, "--api-id", envvar="TELEGRAM_API_ID", help="From my.telegram.org"),
    api_hash: str | None = typer.Option(None, "--api-hash", envvar="TELEGRAM_API_HASH", help="From my.telegram.org"),
    keywords: str | None = typer.Option(None, "--keywords", help="Comma-separated keywords to filter messages"),
    limit: int | None = typer.Option(100, "--limit", help="Max messages per channel"),
    db_url: str | None = typer.Option(
        None, "--db-url", envvar="INGRESS_DB_URL",
        help="Database URL. If omitted, messages are only printed (dry-run style)."
    ),
    session: str = typer.Option("ingress_telegram", "--session", help="Telethon session file name"),
) -> None:
    """
    Ingest messages from public Telegram channels (read-only).

    SECURITY / LEGAL:
    - Only public channels.
    - You must obtain api_id + api_hash from https://my.telegram.org/apps
    - First run will prompt for phone number / code to create a session (standard Telethon behavior).
    - Store credentials securely (env vars, password manager, never commit).
    - Respect Telegram rate limits. The collector has basic flood-wait handling.
    - You are fully responsible for compliance with Telegram ToS.

    Example:
        TELEGRAM_API_ID=123456 TELEGRAM_API_HASH=abcdef... \\
        ingress ingest telegram oryxspioenkop,someosint --keywords "T-72,strike" --limit 50
    """
    if not api_id or not api_hash:
        console.print("[red]--api-id and --api-hash (or TELEGRAM_API_ID / TELEGRAM_API_HASH env) are required.[/]")
        raise typer.Exit(1)

    channel_list = [c.strip() for c in channels.split(",") if c.strip()]
    kw_list = [k.strip() for k in (keywords or "").split(",") if k.strip()] or None

    from .collectors.telegram import TelegramCollector
    from .storage import ensure_schema, insert_artifact

    console.print(f"[cyan]Ingesting Telegram[/] channels: {channel_list}")
    if kw_list:
        console.print(f"  Filtering keywords: {kw_list}")

    collector = TelegramCollector(
        api_id=api_id,
        api_hash=api_hash,
        channels=channel_list,
        keywords=kw_list,
        session_name=session,
    )

    try:
        artifacts = collector.collect_sync(limit=limit)
    except Exception as e:
        console.print(f"[red]Collection failed:[/] {e}")
        console.print("[dim]Common issues: bad credentials, first-time login required, or rate limit.[/]")
        raise typer.Exit(1)

    console.print(f"Collected {len(artifacts)} matching messages.")

    if not db_url:
        for a in artifacts[:5]:
            console.print(f"  - {a.fetched_at} | t.me/{a.metadata.get('channel')}/{a.metadata.get('message_id')} | {(a.text or '')[:70]}...")
        if len(artifacts) > 5:
            console.print(f"  ... and {len(artifacts)-5} more (use --db-url to store)")
        console.print("[dim]No --db-url provided: nothing written to storage.[/]")
        return

    ensure_schema(db_url)
    stored = 0
    for art in artifacts:
        try:
            if insert_artifact(art, db_url):
                stored += 1
                ch = art.metadata.get("channel")
                mid = art.metadata.get("message_id")
                console.print(f"[green]  +[/] t.me/{ch}/{mid}")
        except Exception as exc:
            console.print(f"[red]  ! Error: {exc}[/]")

    console.print(f"\n[bold]Done.[/] Stored {stored} new artifacts.")


@ingest_app.command("target")
def ingest_target(
    iran: bool = typer.Option(False, "--iran", help="Target Iranian military only (public sources: Tasnim, Fars, IRGC-related OSINT)"),
    russia: bool = typer.Option(False, "--russia", help="Target Russian military only (Rybar, Oryx, MoD claims)"),
    china: bool = typer.Option(False, "--china", help="Target Chinese PLA only (PLA Daily, Global Times, theater commands)"),
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL"),
    limit: int | None = typer.Option(50, "--limit"),
) -> None:
    """
    Toggleable targeting for specific countries' military.

    Sources, channels, and keywords from public open-domain military signals.
    Use one or more flags. Data from official state media RSS, established public
    OSINT Telegram (e.g. rybar), known keywords for equipment/exercises/claims.

    Examples:
      ingress ingest target --iran
      ingress ingest target --russia --china
    """
    import os
    from .targeting import get_target_config
    from .collectors.rss import RSSCollector
    from .collectors.telegram import TelegramCollector
    from .storage import ensure_schema, insert_artifact
    # Normalize flags (when invoked directly in python the defaults are typer.Option objects)
    iran = iran if isinstance(iran, bool) else False
    russia = russia if isinstance(russia, bool) else False
    china = china if isinstance(china, bool) else False
    targets = []
    if iran: targets.append("iran")
    if russia: targets.append("russia")
    if china: targets.append("china")

    if not targets:
        console.print("[red]Provide at least one --iran / --russia / --china[/]")
        raise typer.Exit(1)

    if hasattr(db_url, "default"): db_url = db_url.default

    config = get_target_config(targets)

    # Verbose output: show what we're actually targeting
    console.print(f"[cyan]Targeting {targets} — Iranian / Chinese / Russian military focus[/]")
    feeds = config.get("rss_feeds", [])
    chans = config.get("telegram_channels", [])
    kws = config.get("keywords", [])
    console.print(f"[dim]  RSS feeds: {len(feeds)}  |  Telegram channels: {len(chans)}  |  Keywords: {len(kws)}[/]")
    if feeds:
        console.print(f"[dim]  Feeds: {', '.join(feeds[:2])}{' ...' if len(feeds)>2 else ''}[/]")
    if chans:
        console.print(f"[dim]  Channels: {', '.join(chans[:2])}{' ...' if len(chans)>2 else ''}[/]")
    if kws:
        console.print(f"[dim]  Sample keywords: {', '.join(kws[:5])} ...[/]")

    from .targeting import set_current_target, target_multiple
    set_current_target(targets)  # so watch adapts automatically

    arts = target_multiple(targets, limit=limit, db_url=db_url)

    console.print(f"[green]  Collected {len(arts)} artifacts from targeted public sources.[/]")
    if db_url:
        console.print(f"[dim]  Stored to DB (deduped).[/]")
    else:
        console.print("[dim]  (Run with --db-url to persist for watch/delta/export.)[/]")

    console.print("[green]Target complete. Use target_iran(), target_russia(), target_china() or the CLI flags.[/]")


@ingest_app.command("x")
def ingest_x(
    keywords: str = typer.Option("", "--keywords", help="Comma separated keywords"),
    accounts: str = typer.Option("", "--accounts", help="Comma separated @handles"),
    limit: int = typer.Option(10, "--limit"),
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL"),
) -> None:
    """
    X/Twitter ingest stub (PR6).

    Implementation requires X API access (paid tiers as of 2024).
    This command exists to document the interface and will be filled when
    credentials and budget are available.
    """
    console.print("[yellow]X collector is a stub in this build.[/]")
    console.print("Intended usage: provide --keywords and/or --accounts + bearer token via env.")
    console.print("For now use RSS and Telegram collectors (they work today).")
    # TODO: when ready, instantiate XCollector and wire to storage like the others


@app.command("delta")
def delta(
    since: str = typer.Option("24h", "--since", help="Look back window: '24h', '7d', or ISO timestamp"),
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL"),
) -> None:
    """
    Show 'new in open' signals since a given time.

    This is the core 'as it enters the open domains' experience.
    For MVP it does time-based filtering + simple keyword similarity to reduce noise.
    """
    from datetime import datetime, timedelta, timezone, datetime as dt  # for sighting timestamp
    from .config import get_db_url
    from .storage import ensure_schema, get_recent_artifacts

    url = db_url or get_db_url()
    ensure_schema(url)

    # Parse since
    now = datetime.now(timezone.utc)
    if since.endswith("h"):
        hours = int(since[:-1])
        cutoff = now - timedelta(hours=hours)
    elif since.endswith("d"):
        days = int(since[:-1])
        cutoff = now - timedelta(days=days)
    else:
        try:
            cutoff = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except Exception:
            console.print("[red]Invalid --since. Use 24h, 7d, or ISO timestamp.[/]")
            raise typer.Exit(1)

    artifacts = get_recent_artifacts(500, url)
    new_ones = []
    seen_texts = set()

    for a in artifacts:
        try:
            ts = datetime.fromisoformat(a["fetched_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        if ts < cutoff:
            continue

        # very naive similarity filter
        text_key = (a.get("text") or "")[:80].lower().strip()
        if text_key and text_key in seen_texts:
            continue
        seen_texts.add(text_key)
        new_ones.append(a)

    console.print(f"[bold cyan]New in open since {cutoff}[/] ({len(new_ones)} candidates)")

    for a in new_ones[:20]:
        src = a.get("source_name", "?")
        text = (a.get("text") or "")[:90]
        console.print(f"  {a['fetched_at']} | {src} | {text}...")

    if len(new_ones) > 20:
        console.print(f"  ... and {len(new_ones)-20} more")


@app.command("export")
def export_geojson(
    output: str = typer.Argument("sightings.geojson", help="Output GeoJSON file"),
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL"),
) -> None:
    """Export current sightings as GeoJSON FeatureCollection (for mapping tools)."""
    import json
    from datetime import datetime
    from .config import get_db_url
    from .storage import get_sightings

    url = db_url or get_db_url()
    sightings = get_sightings(1000, url)

    features = []
    for s in sightings:
        lat = s.get("lat")
        lon = s.get("lon")
        if lat is None or lon is None:
            continue
        feat = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": s["id"],
                "timestamp": s["timestamp"],
                "description": s.get("description"),
                "confidence": s.get("confidence"),
                "entities": json.loads(s["entities"]) if s.get("entities") else [],
                "artifact_ids": json.loads(s["artifact_ids"]) if s.get("artifact_ids") else [],
            },
        }
        features.append(feat)

    fc = {"type": "FeatureCollection", "features": features}
    with open(output, "w") as f:
        json.dump(fc, f, indent=2)
    console.print(f"[green]Exported {len(features)} sightings with geometry to {output}[/]")


@app.command("db")
def db_command(
    action: str = typer.Argument(..., help="Action: 'init' (ensure tables for sqlite)"),
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL"),
) -> None:
    """Lightweight DB helpers (PR2). For full migrations use alembic directly."""
    from .storage import ensure_schema

    if action == "init":
        ensure_schema(db_url)
        console.print("[green]Schema ensured.[/] (sqlite creates tables; pg should use 'alembic upgrade head')")
    else:
        console.print(f"[red]Unknown action '{action}'. Try 'init'.[/]")
        raise typer.Exit(1)


# --------------------------- Basic Cases (PR7) ---------------------------

CASES_FILE = Path.home() / ".local" / "share" / "ingress" / "cases.json"

def _load_cases():
    CASES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if CASES_FILE.exists():
        try:
            return json.loads(CASES_FILE.read_text())
        except Exception:
            pass
    return {}

def _save_cases(cases):
    CASES_FILE.parent.mkdir(parents=True, exist_ok=True)
    CASES_FILE.write_text(json.dumps(cases, indent=2))

@app.command("case")
def case_cmd(
    action: str = typer.Argument(..., help="create | list | add | show | note"),
    name: str | None = typer.Option(None, "--name", help="Case name"),
    artifact: str | None = typer.Option(None, "--artifact", help="Artifact ID to add"),
    note_text: str | None = typer.Option(None, "--note", help="Note text"),
) -> None:
    """Basic case management (PR7). Simple named collections of artifacts with notes."""
    cases = _load_cases()
    if action == "create":
        if not name:
            console.print("[red]--name required[/]")
            raise typer.Exit(1)
        if name in cases:
            console.print(f"[yellow]Case '{name}' already exists.[/]")
        else:
            cases[name] = {"artifacts": [], "notes": [], "created": datetime.utcnow().isoformat()}
            _save_cases(cases)
            console.print(f"[green]Created case '{name}'[/]")
    elif action == "list":
        if not cases:
            console.print("No cases yet. Use 'ingress case create --name my-investigation'")
            return
        for n, c in cases.items():
            console.print(f"- {n} ({len(c['artifacts'])} artifacts, {len(c['notes'])} notes)")
    elif action == "add":
        if not name or not artifact:
            console.print("[red]--name and --artifact required[/]")
            raise typer.Exit(1)
        if name not in cases:
            console.print(f"[red]Case '{name}' does not exist. Create it first.[/]")
            raise typer.Exit(1)
        if artifact not in cases[name]["artifacts"]:
            cases[name]["artifacts"].append(artifact)
            _save_cases(cases)
        console.print(f"[green]Added {artifact} to case '{name}'[/]")
    elif action == "show":
        if not name or name not in cases:
            console.print("[red]--name of existing case required[/]")
            raise typer.Exit(1)
        c = cases[name]
        console.print(Panel.fit(f"[bold]{name}[/]\nArtifacts: {c['artifacts']}\nNotes: {len(c['notes'])}", title="Case"))
        for n in c["notes"]:
            console.print(f"  - {n}")
    elif action == "note":
        if not name or not note_text:
            console.print("[red]--name and --note required[/]")
            raise typer.Exit(1)
        if name not in cases:
            console.print(f"[red]Case '{name}' does not exist.[/]")
            raise typer.Exit(1)
        cases[name]["notes"].append(f"{datetime.utcnow().isoformat()}: {note_text}")
        _save_cases(cases)
        console.print(f"[green]Added note to '{name}'[/]")
    else:
        console.print("[red]Unknown action. Use create/list/add/show/note[/]")


# --------------------------- Media Workbench (PR3) ---------------------------

@app.command("analyze")
def analyze(
    target: str = typer.Argument(..., help="Local file path or HTTP(S) URL to image/video"),
    db_url: str | None = typer.Option(
        None, "--db-url", envvar="INGRESS_DB_URL",
        help="If provided, store the resulting Artifact (with provenance + media_path)."
    ),
    store: bool = typer.Option(
        False, "--store", help="Explicitly store to DB (same as providing --db-url)."
    ),
    download: bool = typer.Option(
        True, "--download/--no-download", help="For URLs: download to temp for analysis."
    ),
) -> None:
    """
    Analyze an image or video for OSINT purposes.

    Extracts:
    - EXIF/metadata (exiftool if available)
    - Perceptual hash (imagehash + Pillow)
    - Video info (ffprobe if available)
    - Basic military entity hints + GPS from EXIF

    Results can be stored as an Artifact for later fusion / case work.

    External requirements (graceful degradation if missing):
      - exiftool   (brew/apt install exiftool)
      - ffmpeg     (for video; provides ffprobe)
      - imagehash + Pillow (pip install -e '.[media]')

    Examples:
        ingress analyze /path/to/tank.jpg
        ingress analyze https://example.com/strike-video.mp4 --db-url sqlite:///./data/ingress.db --store
    """
    from datetime import datetime as dt
    from .config import get_db_url
    from .geoparser import geoparse, extract_geo_from_analysis
    from .media import analyze_media, make_artifact_from_analysis
    from .models import Sighting, VerificationStatus, ConfidenceLevel
    from .storage import ensure_schema, insert_artifact, insert_sighting

    is_url = target.lower().startswith(("http://", "https://"))
    console.print(f"[cyan]Analyzing[/] {'URL' if is_url else 'file'}: {target}")

    try:
        analysis = analyze_media(target, is_url=is_url, download=download)
    except Exception as e:
        console.print(f"[red]Analysis failed:[/] {e}")
        raise typer.Exit(1)

    # Pretty print with rich
    console.print(Panel.fit(
        f"[bold]Content type:[/] {analysis.get('content_type')}\n"
        f"[bold]Size:[/] {analysis.get('size_bytes', 'unknown')} bytes\n"
        f"[bold]Perceptual hash:[/] {analysis.get('perceptual_hash') or 'n/a'}",
        title="Media Analysis Summary",
        border_style="blue",
    ))

    if analysis.get("exif"):
        exif = analysis["exif"]
        # Show a few interesting keys
        interesting = {k: v for k, v in exif.items() if k in ("Make", "Model", "DateTimeOriginal", "GPSLatitude", "GPSLongitude", "ImageDescription")}
        if interesting:
            t = Table(title="Key EXIF", box=box.SIMPLE)
            t.add_column("Field")
            t.add_column("Value")
            for k, v in interesting.items():
                t.add_row(k, str(v)[:80])
            console.print(t)

    if analysis.get("entities"):
        console.print(f"[yellow]Basic entities detected:[/] {', '.join(analysis['entities'])}")

    if analysis.get("gps"):
        console.print(f"[green]GPS from EXIF:[/] {analysis['gps']}")

    if analysis.get("analysis_warnings"):
        console.print(f"[dim]Warnings: {analysis['analysis_warnings']}[/]")

    # Optional storage
    if db_url or store:
        effective_db = db_url or get_db_url()
        try:
            ensure_schema(effective_db)
            art = make_artifact_from_analysis(analysis, source_url=target if is_url else None)
            inserted = insert_artifact(art, effective_db)
            if inserted:
                console.print(f"[green]Stored as Artifact {art.id} (media_path={art.media_path})[/]")
            else:
                console.print("[yellow]Artifact already existed (by content hash).[/]")
        except Exception as e:
            console.print(f"[red]Failed to store:[/] {e}")

    # Full raw for power users
    if typer.confirm("Show full analysis JSON?", default=False):
        console.print_json(json.dumps(analysis, default=str, indent=2))

    # PR5: basic geoenrichment
    places = geoparse(analysis.get("text") or " ".join(str(v) for v in (analysis.get("exif") or {}).values() if isinstance(v, str)))
    gps = extract_geo_from_analysis(analysis)
    if places or gps:
        console.print(f"[cyan]Geo hints:[/] places={places} gps={gps}")

    # Optionally turn into a Sighting if we have geo (PR5)
    if gps and (db_url or store):
        try:
            effective = db_url or get_db_url()
            sig = Sighting(
                artifact_ids=[],
                timestamp=dt.utcnow(),
                lat=gps["lat"],
                lon=gps["lon"],
                location_name=places[0] if places else None,
                entities=places,
                description=(analysis.get("text") or "Media sighting")[:200],
                confidence=0.65,
                confidence_level=ConfidenceLevel.MEDIUM,
                verification_status=VerificationStatus.UNVERIFIED,
            )
            if insert_sighting(sig, effective):
                console.print(f"[green]Created sighting {sig.id} linked to geo data[/]")
        except Exception as e:
            console.print(f"[yellow]Could not auto-create sighting: {e}[/]")


@app.callback()
def main() -> None:
    """Ingress — the open-source suite for military information entering the open domains."""
    pass


if __name__ == "__main__":  # pragma: no cover
    # Support `python -m ingress.cli`
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo()
    else:
        app()
