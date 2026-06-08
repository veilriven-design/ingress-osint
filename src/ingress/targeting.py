"""
Country-specific targeting functions focused on the Iranian, Chinese, and Russian militaries.

Sources, keywords, and channels are based on publicly known open sources
(official statements, established OSINT accounts, state media RSS where available).

Toggleable via CLI flags in `ingress ingest target --iran`, `--russia`, `--china`.

These can be combined or used separately. Focus is strictly on publicly available
military-related signals (equipment, exercises, official claims, losses, deployments)
as they enter open domains. No private or non-public data.

Sources curated from public OSINT reports, official sites, and established
channels (e.g. Rybar for Russia, Tasnim/Fars for Iran, PLA Daily/Global Times for China).
"""

from __future__ import annotations
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Artifact


def get_iran_config() -> Dict[str, List[str]]:
    """EXTREMELY IN-DEPTH public sources and keywords for Iranian military (IRGC, Artesh, missile/drone/naval/air programs, units, exercises, claims).
    Sources are publicly known open-domain military OSINT / official statements.
    """
    return {
        "rss_feeds": [
            # Iranian state / military media RSS (public)
            "https://www.tasnimnews.com/en/rss",
            "https://www.farsnews.ir/en/rss",
            "https://www.presstv.ir/rss",  # PressTV (public, covers military)
            "https://www.irna.ir/en/rss",  # IRNA official
            "https://www.iranmonitor.org/feed",  # OSINT dashboard aggregation
        ],
        "telegram_channels": [
            # Public Telegram channels for Iranian military signals (official/state/OSINT)
            "Tasnimnews",
            "FarsNewsAgency",
            "IRIMFA_EN",
            "IranIntl",
            "PressTV",
            # Additional public OSINT for depth (from public reports)
            "Osint613",
            "BashaReport",
        ],
        "keywords": [
            # Extremely deep military terms for Iran (equipment, units, locations, programs)
            "IRGC", "Islamic Revolutionary Guard Corps", "IRGC Navy", "IRGC Aerospace Force", "IRGC-ASF",
            "Artesh", "Islamic Republic of Iran Army", "IRIAF",
            "Shahed", "Shahed-136", "Shahed-131", "Ababil", "Karrar", "F-14 Tomcat Iran",
            "ballistic missile", "cruise missile", "Kheibar Shekan", "Fattah", "Emad", "Sejjil",
            "Quds Force", "Qassem Soleimani", "Strait of Hormuz", "Bandar Abbas", "Kish Island",
            "IRGC drone", "UAV Iran", "missile test Iran", "drone attack", "IRGC claims",
            "Persian Gulf", "Oman Sea", "Chabahar", "Jask", "IRGC missile bases",
            "Mowj class", "Jamaran", "Sahand destroyer",
            "submarine Iran", "Fateh class", "Ghadir", "Younes",
            "helicopter Iran", "Mi-17", "Bell 214", "AH-1 Cobra Iran",
            "air defense Iran", "S-300", "Bavar-373", "Mersad",
            "naval exercise Iran", "Velayat", "Eqtedar", "IRGC wargame",
            "IRGC Quds Force", "missile barrage", "drone swarm Iran", "IRGC electronic warfare"
        ],
        "x_accounts": [
            "IRIMFA_EN",   # Official
            "CENTCOM",     # US posts on Iranian activities
            "Osint613",
            "BashaReport",
            "IntelCrab",   # Known Iran OSINT
        ],
        "description": "EXTREMELY DEEP Iranian military (IRGC/Artesh): missiles (ballistic/cruise), drones (Shahed), naval (IRGCN, Artesh), air defense, exercises, bases, units, official claims. All public sources."
    }


def get_russia_config() -> Dict[str, List[str]]:
    """EXTREMELY IN-DEPTH public sources and keywords for Russian military (MoD, VKS, Navy, Ground Forces, equipment, units, operations, losses, exercises).
    All from public open sources (established OSINT like Rybar, Oryx, official MoD).
    """
    return {
        "rss_feeds": [
            "https://eng.mil.ru/rss",  # Russian MoD English official
            "https://www.oryxspioenkop.com/feeds",  # Oryx visual confirmations
            "https://www.mod.gov.ru/rss",  # Russian MoD main
        ],
        "telegram_channels": [
            "rybar",           # Rybar (highly cited for Russian military ops, units, equipment)
            "mod_russia",      # Official Russian MoD (public)
            "zvezdanews",      # Zvezda (MoD media)
            # More public OSINT for depth
            "ReverseSideOfTheMedal",
        ],
        "keywords": [
            # Extremely deep terms: equipment, specific units, operations, losses, districts
            "T-72", "T-72B3", "T-80", "T-80BV", "T-90", "T-90M", "BMP-2", "BMP-3", "BTR-82A", "MT-LB",
            "Su-35", "Su-27", "Su-30", "Su-34", "MiG-29", "MiG-31", "Tu-95", "Tu-22M3",
            "Iskander", "Kalibr", "Kinzhal", "S-400", "S-300", "Pantsir", "Lancet", "Orlan-10",
            "Russian MoD", "VKS", "Russian Aerospace Forces", "Russian Navy", "Black Sea Fleet", "Northern Fleet",
            "Oryx", "Russian losses", "visually confirmed", "T-72 destroyed",
            "Wagner", "PMC", "Eastern Military District", "Central Military District", "Western MD", "Southern MD",
            "1st Guards Tank Army", "2nd Guards Motor Rifle Division", "76th Guards Air Assault", "106th Airborne",
            "Russian electronic warfare", "UAV", "drone strike Russia",
            "Black Sea Fleet", "Admiral Makarov", "Moskva", "Ropucha class", "Kalibr launch",
            "Wagner Group", "Storm-Z", "Russian artillery", "Grad", "Uragan", "Smerch",
            "Russian air defense", "S-400 battery", "Mi-8", "Ka-52", "Mi-28"
        ],
        "x_accounts": [
            "mod_russia",  # Official
            "oryxspioenkop",  # 
            "zvezdanews",
        ],
        "description": "EXTREMELY DEEP Russian military: specific equipment (T-72B3, Su-35, Iskander, Lancet), units (1st GTA, VDV divisions), fleets, districts, losses (Oryx), official claims, electronic warfare, UAVs. Public OSINT + MoD."
    }


def get_china_config() -> Dict[str, List[str]]:
    """EXTREMELY IN-DEPTH public sources and keywords for Chinese PLA (Eastern/Western/Southern/Northern/Central Theater Commands, Navy, Air Force, Rocket Force, exercises in Taiwan/SCS, equipment, units, drills).
    All public (PLA Daily, Global Times, official MSA announcements, CGTN).
    """
    return {
        "rss_feeds": [
            "http://eng.chinamil.com.cn/rss",  # PLA Daily English official
            "https://www.globaltimes.cn/rss",  # Global Times (PLA coverage)
            "https://www.cgtn.com/rss",        # CGTN
            "https://www.msa.gov.cn/rss",      # Maritime Safety Admin (drill announcements)
        ],
        "telegram_channels": [
            # Public for PLA
            "globaltimesnews",
            "CGTNOfficial",
        ],
        "keywords": [
            # Extremely deep terms: specific units, equipment, exercises, locations
            "PLA", "People's Liberation Army", "Eastern Theater Command", "Western Theater Command",
            "Southern Theater Command", "Northern Theater Command", "Central Theater Command",
            "PLA Navy", "PLAN", "Type 055", "Type 052D", "Type 003", "Shandong", "Liaoning", "Fujian carrier",
            "J-20", "J-16", "J-10", "H-6", "H-6K", "Y-20", "KJ-500",
            "DF-21", "DF-26", "DF-17", "DF-41", "PLA Rocket Force",
            "Taiwan Strait", "South China Sea", "East China Sea", "Philippine Sea",
            "military drill China", "PLA exercise", "Joint Sword", "Strait Thunder",
            "PLA amphibious", "Type 075", "Type 071",
            "US warship Taiwan Strait", "Japanese destroyer SCS", "Australian warship",
            "PLA Air Force", "PLAAF", "PLA Navy exercise", "carrier strike group China",
            "Dongfeng missile", "hypersonic China", "PLA electronic warfare",
            "Fujian Province", "Guangdong", "Hainan", "Zhanjiang", "Qingdao",
            "PLA Marine Corps", "PLAMC", "amphibious assault", "island landing drill"
        ],
        "x_accounts": [
            "globaltimesnews",
            "CGTNOfficial",
            "ChinaMilitary",  # PLA media
        ],
        "description": "EXTREMELY DEEP Chinese PLA: Theater Commands, specific ships (Type 055, Shandong), aircraft (J-20), missiles (DF-21/26), exercises (Taiwan Strait, SCS), units (Marine Corps, Rocket Force), official drills/announcements. Public sources."
    }


def get_all_targets() -> Dict[str, Dict[str, List[str]]]:
    """Return all country configs for combined use."""
    return {
        "iran": get_iran_config(),
        "russia": get_russia_config(),
        "china": get_china_config(),
    }


def get_target_config(countries: List[str]) -> Dict[str, List[str]]:
    """
    Merge configs for the requested countries (toggleable).
    Example: countries=["iran", "russia"] returns combined sources/keywords.
    """
    all_configs = get_all_targets()
    merged = {"rss_feeds": [], "telegram_channels": [], "keywords": [], "x_accounts": [], "description": ""}
    for country in countries:
        if country in all_configs:
            cfg = all_configs[country]
            merged["rss_feeds"].extend(cfg["rss_feeds"])
            merged["telegram_channels"].extend(cfg["telegram_channels"])
            merged["keywords"].extend(cfg["keywords"])
            merged["x_accounts"].extend(cfg["x_accounts"])
            merged["description"] += f" {cfg['description']}"
    # Dedup
    for k in ["rss_feeds", "telegram_channels", "keywords", "x_accounts"]:
        merged[k] = list(dict.fromkeys(merged[k]))  # preserve order, unique
    return merged


# --- High-level toggleable targeting functions ---
# Focused on Iranian, Chinese, and Russian militaries using public open sources
# (official state media, established public OSINT channels like Rybar, etc.).
# No synthetic/fake data.

def _run_target_collectors(config: Dict[str, List[str]], limit: int = 50, db_url: Optional[str] = None) -> List["Artifact"]:
    """Internal: run RSS + Telegram (if creds) with the given config."""
    from .collectors.rss import RSSCollector
    from .storage import ensure_schema, insert_artifact
    artifacts: List["Artifact"] = []

    # RSS (feeds + keywords)
    if config.get("rss_feeds"):
        rss = RSSCollector(config["rss_feeds"], keywords=config.get("keywords"))
        arts = rss.collect(limit=limit)
        artifacts.extend(arts)
        if db_url:
            ensure_schema(db_url)
            for a in arts:
                insert_artifact(a, db_url)  # dedup inside

    # Telegram (public channels, requires env creds)
    if config.get("telegram_channels"):
        import os
        api_id = int(os.environ.get("TELEGRAM_API_ID", 0))
        api_hash = os.environ.get("TELEGRAM_API_HASH", "")
        if api_id and api_hash:
            from .collectors.telegram import TelegramCollector
            tg = TelegramCollector(
                api_id, api_hash,
                channels=config["telegram_channels"],
                keywords=config.get("keywords")
            )
            arts = tg.collect_sync(limit=limit)
            artifacts.extend(arts)
            if db_url:
                for a in arts:
                    insert_artifact(a, db_url)

    return artifacts


def target_iran(limit: int = 50, db_url: Optional[str] = None) -> List["Artifact"]:
    """Target Iranian military only. Returns Artifacts from public sources.
    Toggle via CLI: ingress ingest target --iran
    """
    config = get_iran_config()
    return _run_target_collectors(config, limit=limit, db_url=db_url)


def target_russia(limit: int = 50, db_url: Optional[str] = None) -> List["Artifact"]:
    """Target Russian military only. Returns Artifacts from public sources.
    Toggle via CLI: ingress ingest target --russia
    """
    config = get_russia_config()
    return _run_target_collectors(config, limit=limit, db_url=db_url)


def target_china(limit: int = 50, db_url: Optional[str] = None) -> List["Artifact"]:
    """Target Chinese PLA only. Returns Artifacts from public sources.
    Toggle via CLI: ingress ingest target --china
    """
    config = get_china_config()
    return _run_target_collectors(config, limit=limit, db_url=db_url)


def target_multiple(countries: List[str], limit: int = 50, db_url: Optional[str] = None) -> List["Artifact"]:
    """Toggleable multi-target. E.g. countries=['iran', 'russia'].
    All data from public sources.
    """
    config = get_target_config(countries)
    return _run_target_collectors(config, limit=limit, db_url=db_url)


# --- Current target persistence (so `watch` adapts to last `ingest target`) ---
import json
from pathlib import Path

_TARGET_STATE = Path.home() / ".local" / "share" / "ingress" / "current_target.json"

def set_current_target(countries: List[str]) -> None:
    """Persist the current target focus (e.g. ['iran'])."""
    _TARGET_STATE.parent.mkdir(parents=True, exist_ok=True)
    with open(_TARGET_STATE, "w") as f:
        json.dump({"targets": countries or []}, f)

def get_current_target() -> List[str]:
    """Return the last set target(s), e.g. ['iran'] or [] if none."""
    if not _TARGET_STATE.exists():
        return []
    try:
        with open(_TARGET_STATE) as f:
            data = json.load(f)
        return data.get("targets", [])
    except Exception:
        return []
