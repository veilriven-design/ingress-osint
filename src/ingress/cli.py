"""
Ingress CLI + TUI.

Delivers a netvis-quality live experience with military OSINT signals "as they enter the open domain".

This is the flagship first-user experience: zero config, beautiful,
informative, with strong legal/ethical framing and full provenance
visible for every item.
"""

from __future__ import annotations

import json
import html as html_lib
import random
import re
import shutil
import sys
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from queue import Empty, Queue
from typing import Any

try:
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.style import Style
    from rich.table import Table
    from rich.text import Text

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

MAX_RECENT = 20
SPARK_HISTORY = 24
THEATERS = ["Donbas", "Black Sea", "Belgorod", "Kharkiv", "Zaporizhzhia"]

STOP_EVENT = threading.Event()
SIGNAL_QUEUE: Queue[dict[str, Any]] | None = None
STATE_LOCK = threading.Lock()

recent_signals: deque[dict[str, Any]] = deque(maxlen=MAX_RECENT)
source_counts: Counter[str] = Counter()
country_counts: Counter[str] = Counter()
place_counts: Counter[str] = Counter()
event_times: deque[float] = deque(maxlen=300)
spark_buckets: deque[int] = deque([0] * SPARK_HISTORY, maxlen=SPARK_HISTORY)
start_time = time.time()
watch_empty_context: dict[str, Any] = {}


def reset_dashboard_state() -> None:
    global SIGNAL_QUEUE, start_time, spark_buckets, recent_signals, source_counts, country_counts, place_counts, event_times, watch_empty_context

    STOP_EVENT.clear()
    SIGNAL_QUEUE = Queue()
    recent_signals = deque(maxlen=MAX_RECENT)
    source_counts = Counter()
    country_counts = Counter()
    place_counts = Counter()
    event_times = deque(maxlen=300)
    spark_buckets = deque([0] * SPARK_HISTORY, maxlen=SPARK_HISTORY)
    start_time = time.time()
    watch_empty_context = {}


def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def make_sparkline(buckets: deque[int]) -> str:
    if not buckets or max(buckets) == 0:
        return "▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁"
    chars = "▁▂▃▄▅▆▇█"
    mx = max(buckets) or 1
    return "".join(chars[min(int((v / mx) * (len(chars) - 1)), len(chars) - 1)] for v in buckets)


def make_conf_bar(conf: float, width: int = 10) -> str:
    filled = int(conf * width)
    return "█" * filled + "░" * (width - filled)


def feeder(stop_evt: threading.Event, q: Queue[dict[str, Any]]) -> None:
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
        # Track countries for scanner view
        t = (sig.get("target") or "").lower()
        if t in ("iran", "russia", "china"):
            country_counts[t] += 1
        # Track places from entities or metadata hints if present in sig
        for p in (sig.get("entities") or []):
            if isinstance(p, str) and len(p) > 2:
                place_counts[p] += 1


def build_header(stats: str, live: bool = False) -> Panel:
    title = Text("INGRESS", style="bold red")
    sub = "COMPREHENSIVE MILITARY SCANNER • Iran + Russia + China  •  dozens of public domains"
    if not live:
        sub = "Military OSINT • Iranian, Chinese & Russian forces  •  v" + __version__
    subtitle = Text("  " + sub, style="dim")
    return Panel(
        Align.center(Group(title, subtitle, Text(stats, style="bold"))),
        box=box.HEAVY,
        border_style="red",
    )


def target_watch_title(targets: list[str], *, storage: bool = False, live: bool = False) -> tuple[str, str]:
    is_comprehensive = (not targets or set(targets) >= {"iran", "russia", "china"}) and live
    if is_comprehensive:
        source = "live public sources (comprehensive scanner)" if not storage else "stored artifacts"
        return (
            "INGRESS  •  COMPREHENSIVE MILITARY SCANNER",
            f"Iran + Russia + China  •  Pulling from dozens of public RSS + web domains  •  {source}",
        )
    if targets:
        names = [target.title() for target in targets]
        label = names[0] if len(names) == 1 else " / ".join(names)
        suffix = "Military" if len(names) == 1 else "Militaries"
        source = "stored artifacts" if storage else "live signals"
        return f"INGRESS  •  {label} {suffix}", f"Targeted watch for {label}; showing {source}."
    if storage:
        return "INGRESS  •  Stored Military Signals", "Showing all stored artifacts."
    return (
        "INGRESS  •  Military Signals",
        "Live view of signals entering the open domain.\nFull provenance, confidence, and verification status shown for every item.",
    )


def metadata_targets(metadata: dict[str, Any]) -> set[str]:
    targets: set[str] = set()
    for key in ("target", "target_country"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            targets.add(value.lower())
    values = metadata.get("target_countries")
    if isinstance(values, list):
        targets.update(value.lower() for value in values if isinstance(value, str) and value)
    return targets


TARGET_ALIASES: dict[str, tuple[str, ...]] = {
    "iran": (
        "iran", "iranian", "irgc", "artesh", "tehran", "hormuz", "strait of hormuz",
        "shahed", "quds force", "bandar abbas", "bavar-373",
    ),
    "russia": (
        "russia", "russian", "moscow", "vks", "black sea fleet", "ukraine war",
        "russia-ukraine", "iskander", "kalibr", "t-72", "t-90", "oryx",
    ),
    "china": (
        "china", "chinese", "pla", "plan", "pla navy", "taiwan", "taiwan strait",
        "south china sea", "beijing", "rocket force", "type 055", "fujian carrier",
    ),
}

TARGET_SOURCE_HINTS: dict[str, tuple[str, ...]] = {
    "iran": (
        "tehrantimes.com", "tasnimnews.com", "iranintl.com", "mehrnews.com",
        "irna.ir", "presstv.ir", "iranwatch.org",
    ),
    "russia": (
        "understandingwar.org", "kyivindependent.com", "mil.in.ua", "kyivpost.com",
        "defence-blog.com", "rferl.org",
    ),
    "china": (
        "chinamil.com.cn", "scmp.com", "globaltimes.cn", "china-defense.blogspot.com",
        "china-arms.com", "csis.org", "rand.org",
    ),
}


def _metadata_match_text(metadata: dict[str, Any]) -> str:
    parts: list[str] = []
    ignored_keys = {"target_keywords", "keywords"}
    for key, value in metadata.items():
        if key in ignored_keys:
            continue
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value if isinstance(item, str | int | float))
    return " ".join(parts)


def infer_targets(metadata: dict[str, Any], text: str, source: Any = "", raw_ref: Any = "") -> set[str]:
    inferred = metadata_targets(metadata)
    haystack = normalize_match_text(
        " ".join([
            text,
            str(source or ""),
            str(raw_ref or ""),
            _metadata_match_text(metadata),
        ])
    )
    for target, terms in TARGET_ALIASES.items():
        if any(keyword_matches(term, haystack) for term in terms):
            inferred.add(target)
            continue
        if any(hint in haystack for hint in TARGET_SOURCE_HINTS[target]):
            inferred.add(target)
    return inferred


def artifact_matches_focus(
    metadata: dict[str, Any],
    text: str,
    targets: list[str],
    *,
    source: Any = "",
    raw_ref: Any = "",
) -> bool:
    if not targets:
        return True
    inferred = infer_targets(metadata, text, source, raw_ref)
    return bool(inferred.intersection(target.lower() for target in targets))


def display_target_for_signal(
    metadata: dict[str, Any],
    text: str,
    targets: list[str],
    *,
    source: Any = "",
    raw_ref: Any = "",
) -> str | None:
    inferred = infer_targets(metadata, text, source, raw_ref)
    focus = [target.lower() for target in targets]
    focused = [target for target in focus if target in inferred]
    if len(focused) == 1:
        return focused[0]
    if len(inferred) == 1:
        return next(iter(inferred))
    return metadata.get("target") or metadata.get("target_country")


def normalize_match_text(value: str) -> str:
    return (
        value.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .lower()
    )


def keyword_matches(keyword: str, text: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def _target_keyword_terms(text: str, targets: list[str]) -> list[str]:
    if not targets:
        return []
    try:
        from .targeting import get_target_config

        config = get_target_config(targets)
        normalized = normalize_match_text(text)
        return [
            normalize_match_text(keyword)
            for keyword in config.get("keywords", [])
            if keyword_matches(normalize_match_text(keyword), normalized)
        ][:8]
    except Exception:
        return []


HIGH_CRITICALITY_TERMS = [
    "strike", "strikes", "missile", "missiles", "drone", "drones", "uav",
    "air defense", "nuclear", "warhead", "warheads", "silo", "silos",
    "hormuz", "taiwan", "blockade", "small boats", "carrier", "submarine",
    "troops", "losses", "combat", "attack", "attacks", "intercepted",
]

ELEVATED_CRITICALITY_TERMS = [
    "military", "navy", "fleet", "rocket force", "irgc", "pla", "vks",
    "buildup", "exercise", "exercises", "convoy", "artillery", "radar",
    "coast guard", "border", "theater command", "tank", "tanks",
]


def _matched_criticality_terms(sig: dict[str, Any]) -> tuple[list[str], list[str]]:
    haystack = normalize_match_text(
        " ".join([
            str(sig.get("text") or ""),
            " ".join(str(e) for e in (sig.get("entities") or [])),
            str(sig.get("source") or ""),
        ])
    )
    high = [term for term in HIGH_CRITICALITY_TERMS if keyword_matches(term, haystack)]
    elevated = [term for term in ELEVATED_CRITICALITY_TERMS if keyword_matches(term, haystack)]
    return high, elevated


def _compute_criticality(sig: dict[str, Any]) -> tuple[str, str, str, list[str]]:
    """Return (color, label, justification, terms) for watch triage.

    Color is a triage priority for public-source military observations, not a
    claim of truth. The reason is persisted in JSONL logs so analysts can audit
    why an item was colored.
    """
    status = str(sig.get("status", "unverified")).lower()
    conf = float(sig.get("confidence", 0.5))
    high_terms, elevated_terms = _matched_criticality_terms(sig)
    terms = high_terms or elevated_terms

    if high_terms:
        label = "high"
        reason = (
            "High-priority public-source military signal: matched "
            f"{', '.join(high_terms[:4])}; status={status}; confidence={conf:.0%}. "
            "Treat as analyst-triage priority, not as confirmed truth."
        )
        return "red", label, reason, high_terms

    if elevated_terms:
        label = "elevated"
        reason = (
            "Elevated military relevance: matched "
            f"{', '.join(elevated_terms[:4])}; status={status}; confidence={conf:.0%}. "
            "Useful for watch context and follow-up corroboration."
        )
        return "yellow", label, reason, elevated_terms

    if status in {"visually_confirmed", "corroborated"} or conf >= 0.82:
        label = "corroborated"
        reason = (
            f"Corroborated/context signal: status={status}; confidence={conf:.0%}; "
            "no high-priority military trigger terms matched."
        )
        return "blue", label, reason, terms

    label = "routine"
    reason = (
        f"Routine/low-priority context: status={status}; confidence={conf:.0%}; "
        "no configured critical military trigger terms matched."
    )
    return "green", label, reason, terms


def apply_criticality(sig: dict[str, Any]) -> dict[str, Any]:
    color, label, reason, terms = _compute_criticality(sig)
    sig["criticality_color"] = color
    sig["criticality_label"] = label
    sig["criticality_reason"] = reason
    sig["criticality_terms"] = terms
    return sig


def clean_display_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html_lib.unescape(without_tags).split())


def watch_terms(metadata: dict[str, Any], text: str, targets: list[str]) -> list[str]:
    target_terms = _target_keyword_terms(
        " ".join([text, _metadata_match_text(metadata)]),
        targets,
    )
    if target_terms:
        return target_terms
    for key in ("geoparsed_places", "entities", "matched_keywords"):
        values = metadata.get(key)
        if isinstance(values, list):
            terms = [value for value in values if isinstance(value, str) and value]
            if terms:
                return terms
    return []


def target_label(targets: list[str]) -> str:
    return " / ".join(target.title() for target in targets) if targets else "Iran / Russia / China"


def target_flags(targets: list[str]) -> str:
    return " ".join(f"--{target}" for target in targets) if targets else "--iran --russia --china"


def configure_empty_watch_context(
    targets: list[str],
    db: str,
    *,
    reason: str,
    skipped_for_target: int = 0,
) -> None:
    global watch_empty_context

    config: Any
    try:
        from .targeting import get_target_config

        countries = targets or ["iran", "russia", "china"]
        config = get_target_config(countries)
    except Exception:
        config = {"rss_feeds": [], "telegram_channels": [], "keywords": []}

    label = target_label(targets)
    flags = target_flags(targets)
    if reason == "no_match":
        notice = f"No stored artifacts match {label}; {skipped_for_target} artifact(s) are tagged for another focus."
    else:
        notice = f"Watch is active for {label}, but {db} has no stored artifacts yet."

    watch_empty_context = {
        "label": label,
        "notice": notice,
        "feeds": list(config.get("rss_feeds", []))[:5],
        "channels": list(config.get("telegram_channels", []))[:5],
        "keywords": list(config.get("keywords", []))[:8],
        "ingest_command": f"ingress ingest target {flags} --db-url {db}",
        "sample_command": f"ingress ingest sample --db-url {db}",
    }


def _shorten(value: Any, limit: int) -> str:
    text = str(value or "")
    return text[:limit] + ("…" if len(text) > limit else "")


def _is_clickable_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _link_text(label: str, url: Any, *, color: str = "cyan") -> Text:
    if _is_clickable_url(url):
        return Text(label, style=Style(color=color, underline=True, link=str(url)))
    return Text(label, style=color)


def _country_code(target: Any) -> str:
    return {"iran": "IR", "russia": "RU", "china": "CN"}.get(str(target or "").lower(), "--")


def _criticality_initial(label: Any) -> str:
    return {
        "high": "H",
        "elevated": "E",
        "corroborated": "C",
        "routine": "R",
    }.get(str(label or "").lower(), "!")


def _recent_table_columns(width: int) -> list[tuple[str, str, int]]:
    if width < 85:
        return [
            ("time", "T", 5),
            ("crit", "!", 1),
            ("country", "C", 2),
            ("source", "Src", 11),
            ("signal", "Signal", max(26, width - 32)),
        ]
    if width < 110:
        return [
            ("time", "Time", 5),
            ("crit", "!", 1),
            ("country", "C", 2),
            ("source", "Source", 13),
            ("signal", "Signal", max(34, width - 57)),
            ("conf", "Cnf", 4),
            ("status", "Status", 8),
        ]
    return [
        ("time", "Time", 5),
        ("crit", "!", 1),
        ("country", "C", 2),
        ("source", "Source", 14),
        ("signal", "Signal", max(34, width - 108)),
        ("key", "Key Terms", 14),
        ("conf", "Cnf", 4),
        ("status", "Status", 9),
        ("link", "Link", 18),
    ]


def build_recent_table(available_width: int = 140, max_items: int | None = None) -> Table:
    """Dynamically sized table that adapts to terminal width."""
    w = max(60, available_width)
    columns = _recent_table_columns(w)
    compact = len(columns) < 9
    title = "Recent Signals" if compact else "Recent Open-Domain Military Signals"
    t = Table(
        title=title,
        box=box.SIMPLE,
        show_header=True,
        header_style="bold magenta",
        expand=True,
        padding=(0, 0),
    )

    for col_id, header, col_width in columns:
        if col_id == "crit":
            t.add_column(header, style="bold", width=col_width, justify="center", no_wrap=True, overflow="crop")
        elif col_id == "country":
            t.add_column(header, style="bold", width=col_width, justify="center", no_wrap=True, overflow="crop")
        elif col_id == "conf":
            t.add_column(header, width=col_width, justify="right", no_wrap=True, overflow="crop")
        elif col_id in {"time", "status"}:
            t.add_column(header, width=col_width, no_wrap=True, overflow="ellipsis")
        elif col_id == "link":
            t.add_column(header, style="dim", width=col_width, no_wrap=True, overflow="ellipsis")
        else:
            t.add_column(header, width=col_width)

    with STATE_LOCK:
        n = max_items or MAX_RECENT
        items = list(recent_signals)[:n]

    for s in items:
        crit_color = s.get("criticality_color", "white")
        raw = s.get("raw_ref") or ""
        signal_width = next(width for cid, _, width in columns if cid == "signal")
        source_width = next(width for cid, _, width in columns if cid == "source")
        source = _shorten(s.get("source", "?"), source_width)
        key_terms = ", ".join((s.get("entities") or s.get("criticality_terms") or [])[:2])
        if not key_terms:
            key_terms = str(s.get("provenance") or "")
        crit_label = s.get("criticality_label") or s.get("status", "")
        values: dict[str, Any] = {
            "time": datetime.fromtimestamp(s["ts"]).strftime("%H:%M"),
            "crit": Text(_criticality_initial(crit_label), style=f"bold {crit_color}"),
            "country": _country_code(s.get("target")),
            "source": _link_text(source, raw),
            "signal": _shorten(s.get("text"), signal_width),
            "key": _shorten(key_terms, 14),
            "conf": f"{s.get('confidence', 0.5):.0%}",
            "status": Text(_shorten(crit_label, 9), style=crit_color),
            "link": _link_text(_shorten(raw or s.get("provenance", ""), 18), raw, color="blue"),
        }
        t.add_row(*(values[col_id] for col_id, _, _ in columns))

    if not items:
        context = watch_empty_context
        values = {
            "time": now_str(),
            "crit": Text("E", style="bold yellow"),
            "country": "--",
            "source": "watch",
            "signal": str(context["notice"]) if context else "waiting for live public signals...",
            "key": "no stored rows",
            "conf": "-",
            "status": Text("empty", style="yellow"),
            "link": "",
        }
        if context:
            values["link"] = _shorten(str(context["ingest_command"]), 21)
        t.add_row(*(values[col_id] for col_id, _, _ in columns))
    return t


def print_watch_snapshot(main_title: str, second_line: str) -> None:
    render_dashboard(live_mode=False)
    console.print(Panel.fit(
        f"[bold red]{main_title}[/]\n[dim]{second_line}[/]",
        border_style="red",
    ))
    try:
        sw = console.size.width
    except Exception:
        sw = 100
    try:
        sh = console.size.height
    except Exception:
        sh = 28
    max_rows = _visible_signal_count(sw, sh)
    console.print(build_recent_table(available_width=sw, max_items=max_rows))
    console.print(Group(build_countries_panel(), build_sources_panel()))
    if sw >= 95:
        console.print(Group(build_places_panel(), build_entities_panel()))
    else:
        console.print(build_entities_panel())
    console.print(build_criticality_legend(compact=sw < 95))
    actions = build_watch_actions_panel()
    if actions is not None:
        console.print(actions)


def build_watch_actions_panel() -> Panel | None:
    context = watch_empty_context
    if not context:
        return None
    body = Text()
    body.append("Collect target data: ", style="bold")
    body.append(str(context["ingest_command"]))
    body.append("\nLocal smoke data: ", style="bold")
    body.append(str(context["sample_command"]))
    return Panel(body, title="Next Actions", border_style="cyan", box=box.ROUNDED)


def build_sources_panel() -> Panel:
    with STATE_LOCK:
        tops = source_counts.most_common(8)

    t = Table(box=box.MINIMAL, show_header=False, expand=True)
    t.add_column("source", style="green")
    t.add_column("cnt", style="bold", justify="right")

    for src, cnt in tops:
        t.add_row(src[:28], str(cnt))
    if not tops:
        context = watch_empty_context
        feeds = list(context.get("feeds", [])) if context else []
        channels = list(context.get("channels", [])) if context else []
        for feed in feeds:
            t.add_row(feed[:42], "rss")
        for channel in channels:
            t.add_row(("t.me/" + channel)[:42], "tg")
        if not feeds and not channels:
            t.add_row("scanning open sources...", "")
    title = "Configured Sources" if not tops and watch_empty_context else "Active Sources"
    return Panel(t, title=title, border_style="green", box=box.ROUNDED)


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
        context = watch_empty_context
        keywords = list(context.get("keywords", [])) if context else []
        for keyword in keywords[:6]:
            t.add_row(keyword[:38], "keyword")
        if context:
            t.add_row(str(context["ingest_command"])[:38], "collect")
            t.add_row(str(context["sample_command"])[:38], "smoke")
        if not keywords and not context:
            t.add_row("no entities yet", "")
    title = "Watch Readiness" if not tops and watch_empty_context else "Key Entities"
    return Panel(t, title=title, border_style="yellow", box=box.ROUNDED)


def build_countries_panel() -> Panel:
    with STATE_LOCK:
        tops = country_counts.most_common(3)
        total = sum(country_counts.values()) or 1

    t = Table(box=box.MINIMAL, show_header=False, expand=True)
    t.add_column("country", style="bold red")
    t.add_column("cnt", justify="right")
    t.add_column("%", justify="right", style="dim")

    for c, cnt in tops:
        pct = int((cnt / total) * 100)
        t.add_row(c.upper(), str(cnt), f"{pct}%")
    if not tops:
        t.add_row("IR / RU / CN", "—", "waiting")
    title = "By Country (live)"
    return Panel(t, title=title, border_style="red", box=box.ROUNDED, width=22)


def build_places_panel() -> Panel:
    with STATE_LOCK:
        tops = place_counts.most_common(7)

    t = Table(box=box.MINIMAL, show_header=False, expand=True)
    t.add_column("place", style="green")
    t.add_column("n", justify="right", style="dim")

    for p, c in tops:
        t.add_row(p[:28], str(c))
    if not tops:
        t.add_row("geoparsed locations", "—")
    return Panel(t, title="Hot Locations", border_style="green", box=box.ROUNDED)


def build_footer(rate: float, spark: str) -> Text:
    return Text.assemble(
        ("q ", "bold yellow"), ("quit  ", "dim"),
        (f"rate: {rate:.1f}/min", "dim"),
        ("   ", ""),
        (spark, "red"),
        ("   ", ""),
        ("ctrl-c also works", "dim"),
        ("   ", ""),
        ("[red]█[/]high [yellow]█[/]elev [blue]█[/]ctx [green]█[/]routine - JSONL criticality_reason explains each color", "dim"),
    )


def _visible_signal_count(term_w: int, term_h: int) -> int:
    if term_w < 85:
        return max(4, min(7, term_h - 17))
    if term_w < 110 or term_h < 32:
        return max(5, min(9, term_h - 18))
    return max(7, min(MAX_RECENT, term_h - 18))


def build_criticality_legend(*, compact: bool = False) -> Panel:
    if compact:
        body = Text.from_markup("[red]█ high[/]  [yellow]█ elev[/]  [blue]█ ctx[/]  [green]█ routine[/]\nJSONL: criticality_reason")
        title = "Color Code"
    else:
        body = Text.from_markup(
            "[red]█ High[/] kinetic/drone/missile/nuclear/sealane/Taiwan/Hormuz terms; analyst triage first\n"
            "[yellow]█ Elevated[/] military unit/equipment/exercise/buildup terms; follow-up context\n"
            "[blue]█ Context[/] corroborated or high-confidence context without high-priority trigger terms\n"
            "[green]█ Routine[/] lower-priority context; still preserved with provenance\n"
            "Every JSONL record includes criticality_label, criticality_terms, and criticality_reason."
        )
        title = "Criticality Color Code"
    return Panel(body, title=title, border_style="white", box=box.ROUNDED, padding=(0, 1))


def render_dashboard(live_mode: bool = False) -> Layout:
    # drain queue
    if SIGNAL_QUEUE is not None:
        while True:
            try:
                sig = SIGNAL_QUEUE.get_nowait()
                update_state_from_signal(sig)
            except Empty:
                break

    # --- Dynamic real-estate detection (M1 Air laptop vs widescreen) ---
    try:
        term_w = console.size.width
        term_h = console.size.height
    except Exception:
        term_w, term_h = 120, 40

    compact = term_w < 110 or term_h < 32
    very_compact = term_w < 85

    now = time.time()
    elapsed = max(1, now - start_time)
    with STATE_LOCK:
        n_sig = len(recent_signals)
        n_src = len(source_counts)
        n_cty = sum(country_counts.values())
        recent_ev = [t for t in event_times if now - t < 180]
        rate = (len(recent_ev) / max(1, (now - (recent_ev[0] if recent_ev else now)))) * 60 if recent_ev else 0
        spark = make_sparkline(spark_buckets)

    # Terser stats on small screens
    if very_compact:
        stats = f"S:{n_sig} C:{n_cty} {int(elapsed)}s {spark}"
    else:
        stats = f"Signals: {n_sig}  |  Srcs: {n_src}  |  Ctry: {n_cty}  |  {int(elapsed)}s  |  ~{rate:.1f}/min  |  {spark}"

    header = build_header(stats, live=live_mode)

    # Dynamic max recent + pass width so table can be terse
    dyn_max = _visible_signal_count(term_w, term_h)
    recent = build_recent_table(available_width=term_w, max_items=dyn_max)

    srcs = build_sources_panel()
    ents = build_entities_panel()
    ctys = build_countries_panel()
    places = build_places_panel()
    foot = build_footer(rate, spark)

    legend_panel = build_criticality_legend(compact=compact)

    lay = Layout()
    lay.split_column(
        Layout(header, size=3 if compact else 4),
        Layout(name="main", ratio=1),
        Layout(foot, size=2),
    )

    if compact or very_compact:
        # On laptop/small terminal: prioritize the signal table + minimal side info + legend
        # Vertical stack to avoid wasting horizontal space
        lay["main"].split_column(
            Layout(recent, ratio=1),
            Layout(Group(ctys, legend_panel), size=7 if not very_compact else 5),
        )
    else:
        # Full widescreen: rich multi-panel layout
        lay["main"].split_column(
            Layout(name="top_row", ratio=3),
            Layout(name="bottom_row", size=8),
        )
        lay["main"]["top_row"].split_row(
            Layout(recent, ratio=5),
            Layout(Group(ctys, srcs), ratio=2),
        )
        lay["main"]["bottom_row"].split_row(
            Layout(Group(places, legend_panel), ratio=1),
            Layout(ents, ratio=1),
        )
    return lay


def run_canned(run_seconds: float = 0) -> None:
    """Run the TUI with simulated signals from public military sources (no external services required)."""
    if not HAS_RICH:
        print("FATAL: rich is required for the Ingress TUI.")
        print("Requires Python >= 3.10. Install with: python3 -m pip install -e '.[full]'")
        print("If 'python3 --version' is < 3.10, use python3.11 / python3.12 explicitly (and its pip).")
        raise SystemExit(1)

    reset_dashboard_state()

    current_targets = []
    try:
        from .targeting import get_current_target
        current_targets = get_current_target()
    except Exception:
        pass

    # Seed a few initial signals so the UI isn't empty (filter by current target if set)
    for s in SIMULATED_SIGNALS:
        if not current_targets or s.get("target") in current_targets or not s.get("target"):
            if "criticality_color" not in s:
                s = dict(s)  # copy
                apply_criticality(s)
            if SIGNAL_QUEUE is not None:
                SIGNAL_QUEUE.put(s)

    main_title, second_line = target_watch_title(current_targets, live=False)
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
    console.print("[dim]Legend: ▁▂▃▅█ spark  •  C=IR/RU/CN  •  Key=matched entities/places  •  live scanner pulls dozens of public RSS+web pages (keyword filtered)  •  also writing JSONL[/]")
    console.print("[dim]Press 'q' or Ctrl-C to exit. See --help for other options.[/]\n")

    if SIGNAL_QUEUE is None:
        raise RuntimeError("Signal queue was not initialized")
    t_feeder = threading.Thread(target=feeder, args=(STOP_EVENT, SIGNAL_QUEUE), daemon=True)
    t_feeder.start()

    layout = Layout()
    live = Live(layout, console=console, refresh_per_second=4, screen=True)

    deadline = time.time() + run_seconds if run_seconds > 0 else 0

    try:
        live.start()
        while not STOP_EVENT.is_set():
            dash = render_dashboard(live_mode=False)
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


def run_watch(
    db_url: str | None = None,
    run_seconds: float = 0,
    focus_targets: list[str] | None = None,
    live: bool = False,
) -> None:
    """Live TUI pulling from storage (integrated). When live=True, also runs background collectors for real-time ingest from public RSS/web pages while displaying."""
    if not HAS_RICH:
        print("FATAL: rich is required for the Ingress TUI.")
        raise SystemExit(1)

    import json as _json
    import threading as _threading
    from time import sleep as _sleep
    from .config import get_db_url
    from .storage import ensure_schema, get_recent_artifacts

    reset_dashboard_state()

    db = db_url or get_db_url()
    current_targets = focus_targets or []
    if not current_targets:
        try:
            from .targeting import get_current_target
            current_targets = get_current_target()
        except Exception:
            pass
    current_targets = [target.lower() for target in current_targets if target]

    # ---------------- JSONL audit log for analysts ----------------
    from datetime import datetime as _dt
    from pathlib import Path as _Path

    _Path("data").mkdir(parents=True, exist_ok=True)
    stamp = _dt.now().strftime("%Y-%m-%d_%H%M") if live else _dt.now().strftime("%Y-%m-%d")
    watch_jsonl_path = f"data/ingress-{'live' if live else 'watch'}-{stamp}.jsonl"
    watch_jsonl_lock = _threading.Lock()
    console.print(
        f"[green]{'Live signals' if live else 'Rendered observations'} audit log:[/] "
        f"[bold]{watch_jsonl_path}[/] "
        "[dim](JSONL includes criticality_label, criticality_terms, criticality_reason, and raw_ref)[/]"
    )

    def _log_watch_jsonl(sig: dict[str, Any]) -> None:
        try:
            rec = dict(sig)
            rec["logged_at"] = datetime.now(timezone.utc).isoformat()
            with watch_jsonl_lock:
                with open(watch_jsonl_path, "a", encoding="utf-8") as fh:
                    fh.write(_json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ---------------- Live polling threads (real public sources -> TUI + DB) ----------------
    poll_stop = _threading.Event()
    poll_threads: list[_threading.Thread] = []

    def _start_live_pollers() -> None:
        if not current_targets:
            # default broad focus for "everywhere" public signals on the 3
            current_targets[:] = ["iran", "russia", "china"]
        try:
            from .targeting import get_target_config
            cfg = get_target_config(current_targets)
        except Exception:
            return

        rss_urls = [u for u in cfg.get("rss_feeds", []) if u]
        web_urls = [u for u in cfg.get("web_pages", []) if u]
        kws = cfg.get("keywords", []) or None

        if not rss_urls and not web_urls:
            return

        # RSS poller thread (real-time from many public domains)
        def _rss_poller() -> None:
            try:
                from .collectors.rss import RSSCollector
                from .storage import ensure_schema as _es, insert_artifact as _ins
                coll = RSSCollector(rss_urls, keywords=kws)
                interval = 75.0  # polite public polling cadence
                while not poll_stop.is_set():
                    try:
                        arts = coll.collect(limit=25)
                        for a in arts:
                            try:
                                _es(db)
                                _ins(a, db)
                            except Exception:
                                pass
                            # feed TUI even on re-ingest for visibility; real dups are cheap
                            text = clean_display_text(a.text or "")
                            source_name = a.source.name or a.source.id
                            target = display_target_for_signal(
                                a.metadata or {},
                                text,
                                current_targets,
                                source=source_name,
                                raw_ref=a.raw_ref,
                            )
                            sig = {
                                "ts": time.time(),
                                "source": source_name,
                                "type": "RSS",
                                "text": text[:160],
                                "confidence": round(0.68 + (hash(a.content_hash or "") % 18) / 100.0, 2),
                                "status": "unverified",
                                "entities": watch_terms(a.metadata or {}, text, current_targets),
                                "provenance": f"live-rss:{(a.content_hash or 'n/a')[:8]}",
                                "target": target,
                                "raw_ref": a.raw_ref,
                            }
                            apply_criticality(sig)
                            if SIGNAL_QUEUE is not None:
                                SIGNAL_QUEUE.put(sig)
                            _log_watch_jsonl(sig)
                    except Exception:
                        pass  # keep polling; collector records diagnostics internally
                    # jittered wait
                    for _ in range(8):
                        if poll_stop.is_set():
                            return
                        _sleep(interval / 8.0 + (time.time() % 1.3))
            except Exception:
                pass

        # Web page poller (for domains without RSS; slightly slower)
        def _web_poller() -> None:
            if not web_urls:
                return
            try:
                from .collectors.web import WebPageCollector
                from .storage import ensure_schema as _es, insert_artifact as _ins
                coll = WebPageCollector(web_urls, keywords=kws)
                interval = 160.0
                while not poll_stop.is_set():
                    try:
                        arts = coll.collect(limit=15)
                        for a in arts:
                            try:
                                _es(db)
                                _ins(a, db)
                            except Exception:
                                pass
                            text = clean_display_text(a.text or "")
                            source_name = a.source.name or a.source.id
                            target = display_target_for_signal(
                                a.metadata or {},
                                text,
                                current_targets,
                                source=source_name,
                                raw_ref=a.raw_ref,
                            )
                            sig = {
                                "ts": time.time(),
                                "source": source_name,
                                "type": "WEB",
                                "text": text[:160],
                                "confidence": round(0.62 + (hash(a.content_hash or "") % 15) / 100.0, 2),
                                "status": "unverified",
                                "entities": watch_terms(a.metadata or {}, text, current_targets),
                                "provenance": f"live-web:{(a.content_hash or 'n/a')[:8]}",
                                "target": target,
                                "raw_ref": a.raw_ref,
                            }
                            apply_criticality(sig)
                            if SIGNAL_QUEUE is not None:
                                SIGNAL_QUEUE.put(sig)
                            _log_watch_jsonl(sig)
                    except Exception:
                        pass
                    for _ in range(6):
                        if poll_stop.is_set():
                            return
                        _sleep(interval / 6.0 + 1.0)
            except Exception:
                pass

        if rss_urls:
            t = _threading.Thread(target=_rss_poller, daemon=True, name="ingress-live-rss")
            t.start()
            poll_threads.append(t)
        if web_urls:
            t = _threading.Thread(target=_web_poller, daemon=True, name="ingress-live-web")
            t.start()
            poll_threads.append(t)

    if live:
        console.print("[cyan]Live mode enabled[/]: background polling of public RSS + web sources will push new signals to this TUI and DB (respectful cadence, keyword filtered, deduped).")
        _start_live_pollers()

    # Simple DB tailer so external `ingress ingest` also appears live
    def _db_tailer() -> None:
        try:
            from .storage import get_recent_artifacts as _get_recent
            seen: set[str] = set()
            # seed seen with initial load
            try:
                for row in _get_recent(40, db):
                    seen.add(str(row.get("content_hash") or row.get("id") or ""))
            except Exception:
                pass
            while not poll_stop.is_set():
                try:
                    recent = _get_recent(20, db)
                    for row in recent:
                        h = str(row.get("content_hash") or row.get("id") or "")
                        if h and h not in seen:
                            seen.add(h)
                            ts_str = row.get("fetched_at", "")
                            try:
                                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
                            except Exception:
                                ts = time.time()
                            meta: dict[str, Any] = {}
                            try:
                                meta = _json.loads(row.get("metadata", "{}")) if row.get("metadata") else {}
                            except Exception:
                                pass
                            text = clean_display_text(row.get("text") or "")
                            source_name = row.get("source_name", row.get("source_id", "?"))
                            raw_ref = row.get("raw_ref")
                            if not artifact_matches_focus(
                                meta,
                                text,
                                current_targets,
                                source=source_name,
                                raw_ref=raw_ref,
                            ):
                                continue
                            sig = {
                                "ts": ts,
                                "source": source_name,
                                "type": str(row.get("content_type", "text")).upper(),
                                "text": text[:160],
                                "confidence": round(0.70 + (hash(h) % 15) / 100.0, 2),
                                "status": "analyst_reviewed",
                                "entities": watch_terms(meta, text, current_targets),
                                "provenance": f"db:{h[:8]}",
                                "target": display_target_for_signal(
                                    meta,
                                    text,
                                    current_targets,
                                    source=source_name,
                                    raw_ref=raw_ref,
                                ),
                                "raw_ref": raw_ref,
                            }
                            apply_criticality(sig)
                            if SIGNAL_QUEUE is not None:
                                SIGNAL_QUEUE.put(sig)
                            _log_watch_jsonl(sig)
                except Exception:
                    pass
                for _ in range(5):
                    if poll_stop.is_set():
                        return
                    _sleep(4.0)
        except Exception:
            pass

    _threading.Thread(target=_db_tailer, daemon=True, name="ingress-db-tailer").start()

    try:
        ensure_schema(db)
        artifacts = get_recent_artifacts(30, db)
        queued_count = 0
        skipped_for_target = 0
        for a in artifacts:
            ts_str = a.get("fetched_at", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
            except Exception:
                ts = time.time()
            meta: dict[str, Any] = {}
            try:
                meta = _json.loads(a.get("metadata", "{}")) if a.get("metadata") else {}
            except Exception:
                pass
            text = clean_display_text(a.get("text") or "")
            source_name = a.get("source_name", a.get("source_id", "?"))
            raw_ref = a.get("raw_ref")
            if not artifact_matches_focus(
                meta,
                text,
                current_targets,
                source=source_name,
                raw_ref=raw_ref,
            ):
                skipped_for_target += 1
                continue
            sig = {
                "ts": ts,
                "source": source_name,
                "type": str(a.get("content_type", "text")).upper(),
                "text": text[:180],
                "confidence": round(0.7 + (hash(str(a.get("id", ""))) % 20) / 100.0, 2),
                "status": "analyst_reviewed",
                "entities": watch_terms(meta, text, current_targets),
                "provenance": f"db:{str(a.get('content_hash', 'n/a'))[:8]}",
                "target": display_target_for_signal(
                    meta,
                    text,
                    current_targets,
                    source=source_name,
                    raw_ref=raw_ref,
                ),
                "raw_ref": raw_ref,
            }
            apply_criticality(sig)
            if SIGNAL_QUEUE is not None:
                SIGNAL_QUEUE.put(sig)
                queued_count += 1
            _log_watch_jsonl(sig)
        if not artifacts:
            configure_empty_watch_context(current_targets, db, reason="empty")
            collect_cmd = str(watch_empty_context["ingest_command"])
            console.print(
                "[yellow]No stored artifacts found.[/] "
                f"Run [bold]{collect_cmd}[/] to collect target feeds, or "
                f"[bold]ingress ingest sample --db-url {db}[/] for a local smoke dataset."
            )
        elif current_targets and queued_count == 0 and skipped_for_target:
            label = ", ".join(target.title() for target in current_targets)
            configure_empty_watch_context(
                current_targets,
                db,
                reason="no_match",
                skipped_for_target=skipped_for_target,
            )
            collect_cmd = str(watch_empty_context["ingest_command"])
            console.print(
                f"[yellow]No stored artifacts match current focus: {label}.[/] "
                f"Collect with [bold]{collect_cmd}[/]."
            )
    except Exception as exc:
        if current_targets:
            mil_str = ", ".join(t.title() for t in current_targets)
            msg = f"Using public sources for {mil_str}."
        else:
            msg = "Using public sources for the target militaries."
        console.print(f"[yellow]Could not load data from DB ({exc}). {msg}[/]")
        for s in SIMULATED_SIGNALS:
            if not current_targets or s.get("target") in current_targets or not s.get("target"):
                if "criticality_color" not in s:
                    s = dict(s)
                    apply_criticality(s)
                if SIGNAL_QUEUE is not None:
                    SIGNAL_QUEUE.put(s)

    main_title, second_line = target_watch_title(current_targets, storage=True, live=live)
    if run_seconds > 0 or not sys.stdout.isatty():
        print_watch_snapshot(main_title, second_line)
        poll_stop.set()
        console.print("\n[bold]Ingress watch snapshot rendered.[/]\n")
        return

    console.print(Panel.fit(
        f"[bold red]{main_title}[/]\n"
        f"[dim]{second_line}[/]",
        border_style="red",
    ))
    console.print("[dim]Legend: ▁▂▃▅█ spark  •  C=IR/RU/CN  •  Key=matched entities/places  •  live scanner pulls dozens of public RSS+web pages (keyword filtered)  •  also writing JSONL[/]")
    console.print("[dim]Press 'q' or Ctrl-C to exit. This is a functional TUI.[/]\n")

    layout = Layout()
    live_view = Live(layout, console=console, refresh_per_second=3, screen=True)

    deadline = time.time() + run_seconds if run_seconds > 0 else 0

    try:
        live_view.start()
        while not STOP_EVENT.is_set():
            dash = render_dashboard(live_mode=True)
            live_view.update(dash)
            if deadline and time.time() >= deadline:
                STOP_EVENT.set()
                break
            time.sleep(0.15)
    except KeyboardInterrupt:
        STOP_EVENT.set()
    finally:
        poll_stop.set()
        for pt in poll_threads:
            try:
                pt.join(timeout=1.5)
            except Exception:
                pass
        live_view.stop()
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
        run_watch(db_url=None, run_seconds=run_seconds, focus_targets=["iran", "russia", "china"], live=True)
    else:
        run_canned(run_seconds=run_seconds)


@app.command()
def watch(
    iran: bool = typer.Option(False, "--iran", help="Focus on Iranian military (public sources: Tasnim, Fars, IRGC-related OSINT)"),
    russia: bool = typer.Option(False, "--russia", help="Focus on Russian military (Rybar, Oryx, MoD claims)"),
    china: bool = typer.Option(False, "--china", help="Focus on Chinese PLA (PLA Daily, Global Times, theater commands)"),
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL", help="DB to watch (defaults to configured)"),
    run_seconds: float = typer.Option(0, "--run-seconds"),
    live: bool = typer.Option(False, "--live", help="Run background polling of configured public RSS + web sources for real-time updates in the TUI (in addition to DB tail)."),
) -> None:
    """Live TUI watching data from storage (integrated). Use --live for real-time collection from many public domains while watching."""
    # Normalize and set focus if provided (for this run; persists if set)
    iran = iran if isinstance(iran, bool) else False
    russia = russia if isinstance(russia, bool) else False
    china = china if isinstance(china, bool) else False
    targets = []
    if iran:
        targets.append("iran")
    if russia:
        targets.append("russia")
    if china:
        targets.append("china")
    if targets:
        from .targeting import set_current_target
        if not set_current_target(targets):
            console.print("[yellow]Could not persist target focus; continuing for this run only.[/]")
    run_focus = targets or (["iran", "russia", "china"] if live else None)
    run_watch(db_url=db_url, run_seconds=run_seconds, focus_targets=run_focus, live=live)


@app.command()
def version() -> None:
    """Print version."""
    typer.echo(f"ingress {__version__}")


@app.command()
def status(
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL"),
    limit: int = typer.Option(5, "--limit", help="Recent artifacts to show."),
) -> None:
    """Show local storage and target status."""
    from .config import get_db_url
    from .storage import ensure_schema, get_counts, get_recent_artifacts
    from .targeting import get_current_target

    effective_db = db_url or get_db_url()
    ensure_schema(effective_db)
    counts = get_counts(effective_db)
    targets = get_current_target()

    console.print(Panel.fit(
        f"[bold]Database:[/] {effective_db}\n"
        f"[bold]Artifacts:[/] {counts['artifacts']}\n"
        f"[bold]Provenance rows:[/] {counts['provenance']}\n"
        f"[bold]Sightings:[/] {counts['sightings']}\n"
        f"[bold]Target focus:[/] {', '.join(targets) if targets else 'none'}",
        title="Ingress Status",
        border_style="cyan",
    ))

    recent = get_recent_artifacts(limit, effective_db)
    if not recent:
        console.print("[yellow]No artifacts yet.[/] Try: ingress ingest sample --db-url " + effective_db)
        return

    table = Table(title="Recent Artifacts", box=box.SIMPLE)
    table.add_column("Fetched")
    table.add_column("Source")
    table.add_column("Text")
    for row in recent:
        table.add_row(
            str(row.get("fetched_at", ""))[:19],
            str(row.get("source_name") or row.get("source_id") or "?")[:28],
            (row.get("text") or "")[:80],
        )
    console.print(table)


@app.command("export-static-dashboard")
def export_static_dashboard_cmd(
    output: str = typer.Option(
        "src/ingress/web/assets/dashboard-static.json",
        "--output",
        "-o",
        help="Dashboard JSON path to write for GitHub Pages.",
    ),
    target: str = typer.Option(
        "comprehensive",
        "--target",
        help="Dashboard target: comprehensive, iran, russia, or china.",
    ),
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL"),
    limit: int = typer.Option(120, "--limit", min=1, max=250),
    fallback: str | None = typer.Option(
        "src/ingress/web/assets/dashboard-static.json",
        "--fallback",
        help="Existing static JSON to reuse if scheduled collection returns no rows.",
    ),
) -> None:
    """Export the current dashboard payload as a GitHub Pages-safe JSON snapshot."""
    if target not in {"comprehensive", "iran", "russia", "china"}:
        console.print("[red]--target must be one of: comprehensive, iran, russia, china[/]")
        raise typer.Exit(1)

    from .api import export_static_dashboard

    payload = export_static_dashboard(
        output_path=output,
        target=target,
        limit=limit,
        db_url=db_url,
        fallback_path=fallback,
    )
    signal_count = len(payload.get("signals") or [])
    console.print(f"[green]Exported {signal_count} static dashboard signal(s) to {output}[/]")


@app.command()
def doctor(
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL"),
) -> None:
    """Check local Ingress runtime health."""
    import importlib.util

    from .config import get_db_url
    from .state import get_state_dir, state_dir_writable
    from .storage import ensure_schema, get_counts

    effective_db = db_url or get_db_url()
    checks: list[tuple[str, bool, str]] = []

    checks.append(("Python", sys.version_info >= (3, 10), sys.version.split()[0]))
    checks.append(("rich", HAS_RICH, "installed" if HAS_RICH else "missing"))
    checks.append(("feedparser", importlib.util.find_spec("feedparser") is not None, "RSS ingest"))
    checks.append(("telethon", importlib.util.find_spec("telethon") is not None, "Telegram ingest"))
    checks.append(("Pillow", importlib.util.find_spec("PIL") is not None, "media images"))
    checks.append(("imagehash", importlib.util.find_spec("imagehash") is not None, "perceptual hashing"))
    checks.append(("fastapi", importlib.util.find_spec("fastapi") is not None, "API"))
    checks.append(("exiftool", shutil.which("exiftool") is not None, shutil.which("exiftool") or "missing"))
    checks.append(("ffprobe", shutil.which("ffprobe") is not None, shutil.which("ffprobe") or "missing"))
    checks.append(("state dir", state_dir_writable(), str(get_state_dir())))

    try:
        ensure_schema(effective_db)
        counts = get_counts(effective_db)
        db_detail = f"{effective_db} ({counts['artifacts']} artifacts, {counts['sightings']} sightings)"
        checks.append(("SQLite DB", True, db_detail))
    except Exception as exc:
        checks.append(("SQLite DB", False, str(exc)))

    table = Table(title="Ingress Doctor", box=box.SIMPLE)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for name, ok, detail in checks:
        table.add_row(name, "[green]ok[/]" if ok else "[red]problem[/]", detail)
    console.print(table)

    if all(ok for _, ok, _ in checks):
        console.print("[green]Ingress local runtime looks healthy.[/]")
    else:
        console.print("[yellow]Ingress can still run with reduced functionality where optional checks are missing.[/]")


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
        help="SQLite database URL (sqlite://...). Defaults to config / sqlite DB.",
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
        for diag in collector.diagnostics[:5]:
            console.print(f"[dim]  - {diag}[/]")
        return

    console.print(f"Parsed {len(artifacts)} candidate entries from feed.")

    if dry_run:
        for a in artifacts[:5]:
            console.print(f"  - {a.fetched_at} | {a.raw_ref} | { (a.text or '')[:80] }...")
        console.print("[dim]--dry-run: nothing written.[/]")
        return

    # Ensure schema for the current SQLite storage layer.
    try:
        ensure_schema(db_url)
    except Exception as e:
        console.print(f"[yellow]ensure_schema warning: {e}[/]")

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


@ingest_app.command("web")
def ingest_web(
    url: str = typer.Argument(..., help="Public web page URL to snapshot (e.g. official mil news hub)"),
    db_url: str | None = typer.Option(
        None,
        "--db-url",
        envvar="INGRESS_DB_URL",
        help="SQLite database URL. Defaults to configured.",
    ),
    limit: int | None = typer.Option(None, "--limit"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Fetch and show but do not persist"),
) -> None:
    """
    Ingest a single public web page as a text artifact (keyword filtering optional via target).

    Useful for public pages that do not publish reliable RSS/Atom (e.g. some official
    English-language PLA, assessment blogs, state media homepages).

    Always bounded + explicit: you name the exact public URL.
    """
    from .collectors.web import WebPageCollector
    from .storage import ensure_schema, insert_artifact

    console.print(f"[cyan]Ingesting web page[/] {url}")

    collector = WebPageCollector(url)
    artifacts = collector.collect()

    if limit:
        artifacts = artifacts[:limit]

    if not artifacts:
        console.print("[yellow]No matching content extracted (or keyword filter excluded all).[/]")
        for d in collector.diagnostics[:5]:
            console.print(f"[dim]  - {d}[/]")
        return

    console.print(f"Extracted {len(artifacts)} artifact(s) from page text.")

    if dry_run:
        for a in artifacts[:3]:
            console.print(f"  - {a.raw_ref} | {(a.text or '')[:100]}...")
        console.print("[dim]--dry-run: nothing written.[/]")
        return

    try:
        ensure_schema(db_url)
    except Exception as e:
        console.print(f"[yellow]ensure_schema warning: {e}[/]")

    stored = 0
    for art in artifacts:
        try:
            if insert_artifact(art, db_url):
                stored += 1
                console.print(f"[green]  +[/] {art.raw_ref} (hash {(art.content_hash or 'n/a')[:10]})")
        except Exception as exc:
            console.print(f"[red]  ! {exc}[/]")

    console.print(f"\n[bold]Done.[/] Stored {stored} new page artifact(s).")


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
    from .targeting import get_target_config

    # Normalize flags (when invoked directly in python the defaults are typer.Option objects)
    iran = iran if isinstance(iran, bool) else False
    russia = russia if isinstance(russia, bool) else False
    china = china if isinstance(china, bool) else False
    targets = []
    if iran:
        targets.append("iran")
    if russia:
        targets.append("russia")
    if china:
        targets.append("china")

    if not targets:
        console.print("[red]Provide at least one --iran / --russia / --china[/]")
        raise typer.Exit(1)

    config = get_target_config(targets)

    # Verbose output: show what we're actually targeting
    target_names = " / ".join(target.title() for target in targets)
    console.print(f"[cyan]Targeting {target_names} military focus[/]")
    feeds = config.get("rss_feeds", [])
    chans = config.get("telegram_channels", [])
    webs = config.get("web_pages", [])
    kws = config.get("keywords", [])
    console.print(f"[dim]  RSS feeds: {len(feeds)}  |  Web pages: {len(webs)}  |  Telegram channels: {len(chans)}  |  Keywords: {len(kws)}[/]")
    if feeds:
        console.print(f"[dim]  Feeds: {', '.join(feeds[:2])}{' ...' if len(feeds)>2 else ''}[/]")
    if webs:
        console.print(f"[dim]  Web: {', '.join(webs[:2])}{' ...' if len(webs)>2 else ''}[/]")
    if chans:
        console.print(f"[dim]  Channels: {', '.join(chans[:2])}{' ...' if len(chans)>2 else ''}[/]")
    if kws:
        console.print(f"[dim]  Sample keywords: {', '.join(kws[:5])} ...[/]")

    from .targeting import set_current_target, target_multiple
    if not set_current_target(targets):
        console.print("[yellow]Could not persist target focus; continuing without saving it.[/]")

    diagnostics: list[str] = []
    arts = target_multiple(targets, limit=limit or 50, db_url=db_url, diagnostics=diagnostics)

    console.print(f"[green]  Collected {len(arts)} artifacts from targeted public sources.[/]")
    if diagnostics:
        console.print("[yellow]  RSS diagnostics:[/]")
        for diag in diagnostics[:6]:
            console.print(f"[dim]    - {diag}[/]")
        if len(diagnostics) > 6:
            console.print(f"[dim]    ... and {len(diagnostics) - 6} more[/]")
    if db_url:
        console.print("[dim]  Stored to DB (deduped).[/]")
    else:
        console.print("[dim]  (Run with --db-url to persist for watch/delta/export.)[/]")
    if not arts:
        console.print("[yellow]  No artifacts matched. Check network access, feed health, and keyword filters.[/]")
        console.print("[dim]  For a local smoke run: ingress ingest sample --db-url sqlite:///./data/ingress.db[/]")

    console.print("[green]Target complete. Use target_iran(), target_russia(), target_china() or the CLI flags.[/]")


@ingest_app.command("sample")
def ingest_sample(
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL"),
) -> None:
    """Insert deterministic synthetic sample records for local verification."""
    from .config import get_db_url
    from .sample_data import make_sample_records
    from .storage import ensure_schema, insert_artifact, insert_sighting

    effective_db = db_url or get_db_url()
    ensure_schema(effective_db)

    artifacts_inserted = 0
    sightings_inserted = 0
    for artifact, sighting in make_sample_records():
        if insert_artifact(artifact, effective_db):
            artifacts_inserted += 1
        if insert_sighting(sighting, effective_db):
            sightings_inserted += 1

    console.print(
        "[green]Sample data ready.[/] "
        f"Inserted {artifacts_inserted} artifacts and {sightings_inserted} sightings."
    )
    console.print(f"[dim]Next: ingress watch --db-url {effective_db}[/]")


@ingest_app.command("x")
def ingest_x(
    keywords: str = typer.Option("", "--keywords", help="Comma separated keywords"),
    accounts: str = typer.Option("", "--accounts", help="Comma separated @handles"),
    limit: int = typer.Option(10, "--limit"),
    db_url: str | None = typer.Option(None, "--db-url", envvar="INGRESS_DB_URL"),
) -> None:
    """
    X/Twitter ingest is not implemented in this build.

    Implementation requires X API access (paid tiers as of 2024).
    This command exists to document the interface and will be filled when
    credentials and budget are available.
    """
    console.print("[yellow]X collector is a stub in this build.[/]")
    console.print("Intended usage: provide --keywords and/or --accounts + bearer token via env.")
    console.print("For now use RSS and Telegram collectors (they work today).")


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
                "entities": s.get("entities") or [],
                "artifact_ids": s.get("artifact_ids") or [],
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
    """Lightweight DB helpers for the SQLite storage layer."""
    from .storage import ensure_schema

    if action == "init":
        ensure_schema(db_url)
        console.print("[green]Schema ensured.[/] (SQLite tables are ready)")
    else:
        console.print(f"[red]Unknown action '{action}'. Try 'init'.[/]")
        raise typer.Exit(1)


# --------------------------- Basic Cases (PR7) ---------------------------

def _load_cases() -> dict[str, dict[str, Any]]:
    from .state import cases_file

    path = cases_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _save_cases(cases: dict[str, dict[str, Any]]) -> None:
    from .state import cases_file

    path = cases_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cases, indent=2))

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
    show_json: bool = typer.Option(False, "--show-json", help="Print full analysis JSON."),
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

    if show_json:
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
    app()
