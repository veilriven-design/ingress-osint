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

import json
from typing import TYPE_CHECKING, TypedDict

from .state import fallback_target_state_file, target_state_file

if TYPE_CHECKING:
    from pathlib import Path

    from .models import Artifact


class TargetConfig(TypedDict):
    rss_feeds: list[str]
    telegram_channels: list[str]
    keywords: list[str]
    x_accounts: list[str]
    web_pages: list[str]
    description: str


def get_iran_config() -> TargetConfig:
    """Comprehensive public sources for Iranian military (IRGC, Artesh, missile/drone/naval/air, exercises, claims, Quds Force).
    Curated from many public domains (state English services, regional/international defense & ME news, OSINT). Keyword filtered.
    Used by default in 'ingress watch --live' as part of the Iran/Russia/China military scanner.
    """
    return {
        "rss_feeds": [
            # Core public Iran + regional defense coverage (public RSS)
            "https://www.defensenews.com/arc/outboundfeeds/rss/category/global/mideast-africa/?outputType=xml",
            "https://www.tehrantimes.com/rss",
            "https://www.aljazeera.com/xml/rss/all.xml",
            "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
            "https://kyivindependent.com/news-archive/rss/",
            "https://www.realcleardefense.com/rss",
            "https://rss.feedburner.com/defensenews/feed",
            # Iran state / semi-state English public RSS
            "https://www.tasnimnews.com/en/rss/feed/0/7/0/all-stories",
            "https://en.mehrnews.com/rss",
            "https://www.al-monitor.com/rss",
            # Additional high-value public feeds that regularly cover Iranian military activity
            "https://breakingdefense.com/feed/",
            "https://en.irna.ir/rss",
            "https://www.presstv.ir/rss",
            "https://www.middleeasteye.net/feed",
            "https://apnews.com/rss",
            "https://www.militarytimes.com/arc/outboundfeeds/rss/",
            "https://thedrive.com/the-war-zone/rss",
        ],
        "telegram_channels": [
            "Tasnimnews", "FarsNewsAgency", "IRIMFA_EN", "IranIntl", "PressTV",
            "Osint613", "BashaReport",
        ],
        "keywords": [
            # Deep military terms for Iran
            "IRGC", "Islamic Revolutionary Guard Corps", "IRGC Navy", "IRGC Aerospace Force", "IRGC-ASF",
            "Artesh", "Islamic Republic of Iran Army", "IRIAF",
            "Shahed", "Shahed-136", "Shahed-131", "Ababil", "Karrar", "F-14 Tomcat Iran",
            "ballistic missile", "cruise missile", "Kheibar Shekan", "Fattah", "Emad", "Sejjil",
            "Quds Force", "Qassem Soleimani", "Strait of Hormuz", "Bandar Abbas", "Kish Island",
            "IRGC drone", "UAV Iran", "missile test Iran", "drone attack", "IRGC claims",
            "Iran launches drones", "Iranian sites", "Iranian military", "Iranian army",
            "Iran air defense", "air defense Iran", "nuclear sites",
            "Oman Sea", "Chabahar", "Jask", "IRGC missile bases",
            "Mowj class", "Jamaran", "Sahand destroyer",
            "submarine Iran", "Fateh class", "Ghadir", "Younes",
            "helicopter Iran", "Mi-17", "Bell 214", "AH-1 Cobra Iran",
            "S-300", "Bavar-373", "Mersad",
            "naval exercise Iran", "Velayat", "Eqtedar", "IRGC wargame",
            "IRGC Quds Force", "missile barrage", "drone swarm Iran", "IRGC electronic warfare"
        ],
        "x_accounts": [
            "IRIMFA_EN", "CENTCOM", "Osint613", "BashaReport", "IntelCrab",
        ],
        "web_pages": [
            # High-signal public pages (official English, analysis hubs) — explicit & bounded
            "https://www.tasnimnews.com/en",
            "https://www.tehrantimes.com/",
            "https://www.iranintl.com/en",
            "https://en.mehrnews.com/",
            "https://en.irna.ir/",
            "https://www.presstv.ir/",
            "https://www.iranwatch.org/",
        ],
        "description": "Comprehensive Iranian military (IRGC/Artesh): missiles, drones (Shahed), naval, air defense, exercises, bases, Quds Force. Public sources from many domains."
    }


def get_russia_config() -> TargetConfig:
    """Comprehensive public sources for Russian military (MoD, VKS, Navy, Ground Forces, equipment, units, ops, losses, EW, exercises).
    Curated from many public domains (Ukrainian/independent defense reporting, ISW, Western defense pubs, OSINT). Keyword filtered.
    Used by default in 'ingress watch --live' as part of the Iran/Russia/China military scanner.
    """
    return {
        "rss_feeds": [
            # High volume public coverage of Russian forces / Ukraine war (public RSS)
            "https://kyivindependent.com/news-archive/rss/",
            "https://www.defensenews.com/arc/outboundfeeds/rss/category/global/?outputType=xml",
            "https://www.defensenews.com/arc/outboundfeeds/rss/category/land/?outputType=xml",
            "https://www.realcleardefense.com/rss",
            "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
            "https://defence-blog.com/topics/russia-ukraine/feed/",
            "https://kyivindependent.com/rss/",
            "https://rss.feedburner.com/defensenews/feed",
            # ISW and analytical public updates (daily assessments)
            "https://understandingwar.org/rss.xml",
            "https://www.understandingwar.org/rss",
            # Additional strong public sources frequently covering Russian military activity
            "https://breakingdefense.com/feed/",
            "https://mil.in.ua/en/feed/",
            "https://www.kyivpost.com/rss",
            "https://www.militarytimes.com/arc/outboundfeeds/rss/",
            "https://thedrive.com/the-war-zone/rss",
            "https://apnews.com/rss",
            "https://www.rferl.org/api/z$yre",
            "https://www.bbc.com/news/world/europe/rss.xml",
        ],
        "telegram_channels": [
            "rybar", "mod_russia", "zvezdanews", "ReverseSideOfTheMedal",
        ],
        "keywords": [
            # Deep terms for Russian military
            "T-72", "T-72B3", "T-80", "T-80BV", "T-90", "T-90M", "BMP-2", "BMP-3", "BTR-82A", "MT-LB",
            "Su-35", "Su-27", "Su-30", "Su-34", "MiG-29", "MiG-31", "Tu-95", "Tu-22M3",
            "Iskander", "Kalibr", "Kinzhal", "S-400", "S-300", "Pantsir", "Lancet", "Orlan-10",
            "Russia-Ukraine", "Ukraine war", "Russian forces", "Russian troops", "Russian military",
            "Russian army", "Russian drone", "Russian drones", "Russian missile", "Russian missiles",
            "Russian MoD", "VKS", "Russian Aerospace Forces", "Russian Navy", "Black Sea Fleet", "Northern Fleet",
            "Oryx", "Russian losses", "visually confirmed", "T-72 destroyed",
            "Wagner", "PMC", "Eastern Military District", "Central Military District", "Western MD", "Southern MD",
            "1st Guards Tank Army", "2nd Guards Motor Rifle Division", "76th Guards Air Assault", "106th Airborne",
            "Russian electronic warfare", "UAV", "drone strike Russia",
            "Black Sea Fleet", "Admiral Makarov", "Moskva", "Ropucha class", "Kalibr launch",
            "Wagner Group", "Storm-Z", "Russian artillery", "Grad", "Uragan", "Smerch",
            "Russian air defense", "Russian air defense systems", "S-400 battery", "Mi-8", "Ka-52", "Mi-28"
        ],
        "x_accounts": [
            "mod_russia", "oryxspioenkop", "zvezdanews",
        ],
        "web_pages": [
            # High-signal public pages with frequent updates
            "https://understandingwar.org/",
            "https://www.kyivindependent.com/",
            "https://www.realcleardefense.com/",
            "https://defence-blog.com/",
            "https://mil.in.ua/en/",
            "https://www.understandingwar.org/research/russia-ukraine",
            "https://jamestown.org/regions/russia/",
        ],
        "description": "Comprehensive Russian military: equipment (T-72B3 etc), units, fleets, districts, losses (Oryx), EW, UAVs, official claims. Public sources from many domains."
    }


def get_china_config() -> TargetConfig:
    """Comprehensive public sources for Chinese PLA (Theater Commands, PLAN, PLAAF, Rocket Force, exercises in Taiwan Strait/SCS, equipment, drills, buildup).
    Curated from many public domains (SCMP, Defense News Asia, official English PLA site, China defense analysis, think tanks). Keyword filtered.
    Used by default in 'ingress watch --live' as part of the Iran/Russia/China military scanner.
    """
    return {
        "rss_feeds": [
            # Public PLA / China military coverage
            "https://www.defensenews.com/arc/outboundfeeds/rss/category/global/asia-pacific/?outputType=xml",
            "https://www.scmp.com/rss/4/feed",
            "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml",
            "https://www.realcleardefense.com/rss",
            "https://china-defense.blogspot.com/feeds/posts/default",
            "https://www.china-arms.com/feed/",
            "https://rss.feedburner.com/defensenews/feed",
            "https://www.aljazeera.com/xml/rss/all.xml",
            # Additional public English sources that regularly cover PLA / China military developments
            "https://breakingdefense.com/feed/",
            "https://www.globaltimes.cn/rss/china.xml",
            "http://www.news.cn/english/rss/worldrss.xml",
            "https://jamestown.org/feed/",
            "https://www.militarytimes.com/arc/outboundfeeds/rss/",
            "https://thedrive.com/the-war-zone/rss",
            "https://www.csis.org/rss",
            "https://apnews.com/rss",
        ],
        "telegram_channels": [
            "globaltimesnews", "CGTNOfficial",
        ],
        "keywords": [
            # Deep terms for Chinese PLA
            "PLA", "People's Liberation Army", "Eastern Theater Command", "Western Theater Command",
            "Southern Theater Command", "Northern Theater Command", "Central Theater Command",
            "PLA Navy", "PLAN", "Type 055", "Type 052D", "Type 003", "Shandong", "Liaoning", "Fujian carrier",
            "J-20", "J-16", "J-10", "H-6", "H-6K", "Y-20", "KJ-500",
            "DF-21", "DF-26", "DF-17", "DF-41", "PLA Rocket Force",
            "Taiwan Strait", "South China Sea", "East China Sea", "Philippine Sea",
            "Taiwan", "Chinese military", "China's military", "China military", "China's buildup",
            "Chinese navy", "China Coast Guard", "warheads", "nuclear missile", "nuclear missiles",
            "missile silos", "defense spending", "military buildup",
            "military drill China", "PLA exercise", "Joint Sword", "Strait Thunder",
            "PLA amphibious", "Type 075", "Type 071",
            "US warship Taiwan Strait", "Japanese destroyer SCS", "Australian warship",
            "PLA Air Force", "PLAAF", "PLA Navy exercise", "carrier strike group China",
            "Dongfeng missile", "hypersonic China", "PLA electronic warfare",
            "Fujian Province", "Guangdong", "Hainan", "Zhanjiang", "Qingdao",
            "PLA Marine Corps", "PLAMC", "amphibious assault", "island landing drill"
        ],
        "x_accounts": [
            "globaltimesnews", "CGTNOfficial", "ChinaMilitary",
        ],
        "web_pages": [
            # High-signal public pages (official English PLA, analysis, think tanks)
            "http://eng.chinamil.com.cn/",
            "https://www.scmp.com/topics/pla-daily",
            "https://www.scmp.com/asia",
            "https://www.scmp.com/topics/china-military",
            "https://jamestown.org/program/china-brief/",
            "https://www.csis.org/programs/china-power-project",
            "https://www.rand.org/topics/china.html",
        ],
        "description": "Comprehensive Chinese PLA: Theater Commands, ships (Type 055 etc), aircraft (J-20), missiles (DF-21/26), exercises (Taiwan/SCS), Rocket Force, buildup. Public sources from many domains."
    }


def get_all_targets() -> dict[str, TargetConfig]:
    """Return all country configs for combined use."""
    return {
        "iran": get_iran_config(),
        "russia": get_russia_config(),
        "china": get_china_config(),
    }


def get_target_config(countries: list[str]) -> TargetConfig:
    """
    Merge configs for the requested countries (toggleable).
    Example: countries=["iran", "russia"] returns combined sources/keywords.
    """
    all_configs = get_all_targets()
    merged: TargetConfig = {
        "rss_feeds": [],
        "telegram_channels": [],
        "keywords": [],
        "x_accounts": [],
        "web_pages": [],
        "description": "",
    }
    for country in countries:
        if country in all_configs:
            cfg = all_configs[country]
            merged["rss_feeds"].extend(cfg["rss_feeds"])
            merged["telegram_channels"].extend(cfg["telegram_channels"])
            merged["keywords"].extend(cfg["keywords"])
            merged["x_accounts"].extend(cfg["x_accounts"])
            merged["web_pages"].extend(cfg.get("web_pages", []))
            merged["description"] += f" {cfg['description']}"
    merged["rss_feeds"] = list(dict.fromkeys(merged["rss_feeds"]))
    merged["telegram_channels"] = list(dict.fromkeys(merged["telegram_channels"]))
    merged["keywords"] = list(dict.fromkeys(merged["keywords"]))
    merged["x_accounts"] = list(dict.fromkeys(merged["x_accounts"]))
    merged["web_pages"] = list(dict.fromkeys(merged["web_pages"]))
    return merged


# --- High-level toggleable targeting functions ---
# Focused on Iranian, Chinese, and Russian militaries using public open sources
# (official state media, established public OSINT channels like Rybar, etc.).
# No synthetic/fake data.

def _run_target_collectors(
    config: TargetConfig,
    limit: int = 50,
    db_url: str | None = None,
    diagnostics: list[str] | None = None,
    target_countries: list[str] | None = None,
) -> list["Artifact"]:
    """Internal: run RSS + Telegram (if creds) with the given config."""
    from .collectors.rss import RSSCollector
    from .storage import ensure_schema, insert_artifact
    artifacts: list["Artifact"] = []
    targets = [country.lower() for country in (target_countries or [])]

    # RSS (feeds + keywords) - primary real-time capable public source
    if config.get("rss_feeds"):
        rss = RSSCollector(config["rss_feeds"], keywords=config.get("keywords"))
        arts = rss.collect(limit=limit)
        _stamp_artifact_targets(arts, targets)
        if diagnostics is not None:
            diagnostics.extend(rss.diagnostics)
        artifacts.extend(arts)
        if db_url:
            ensure_schema(db_url)
            for a in arts:
                insert_artifact(a, db_url)  # dedup inside

    # Web pages (explicit public pages for sites lacking good RSS; keyword filtered)
    if config.get("web_pages"):
        from .collectors.web import WebPageCollector
        web = WebPageCollector(config["web_pages"], keywords=config.get("keywords"))
        arts = web.collect(limit=limit)
        _stamp_artifact_targets(arts, targets)
        if diagnostics is not None:
            diagnostics.extend(web.diagnostics)
        artifacts.extend(arts)
        if db_url:
            ensure_schema(db_url)
            for a in arts:
                insert_artifact(a, db_url)

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
            _stamp_artifact_targets(arts, targets)
            artifacts.extend(arts)
            if db_url:
                for a in arts:
                    insert_artifact(a, db_url)

    return artifacts


def _stamp_artifact_targets(artifacts: list["Artifact"], countries: list[str]) -> None:
    if not countries:
        return
    for artifact in artifacts:
        metadata = dict(artifact.metadata or {})
        metadata["target_countries"] = countries
        if len(countries) == 1:
            metadata["target_country"] = countries[0]
        artifact.metadata = metadata


def target_iran(
    limit: int = 50,
    db_url: str | None = None,
    diagnostics: list[str] | None = None,
) -> list["Artifact"]:
    """Target Iranian military only. Returns Artifacts from public sources.
    Toggle via CLI: ingress ingest target --iran
    """
    config = get_iran_config()
    return _run_target_collectors(
        config,
        limit=limit,
        db_url=db_url,
        diagnostics=diagnostics,
        target_countries=["iran"],
    )


def target_russia(
    limit: int = 50,
    db_url: str | None = None,
    diagnostics: list[str] | None = None,
) -> list["Artifact"]:
    """Target Russian military only. Returns Artifacts from public sources.
    Toggle via CLI: ingress ingest target --russia
    """
    config = get_russia_config()
    return _run_target_collectors(
        config,
        limit=limit,
        db_url=db_url,
        diagnostics=diagnostics,
        target_countries=["russia"],
    )


def target_china(
    limit: int = 50,
    db_url: str | None = None,
    diagnostics: list[str] | None = None,
) -> list["Artifact"]:
    """Target Chinese PLA only. Returns Artifacts from public sources.
    Toggle via CLI: ingress ingest target --china
    """
    config = get_china_config()
    return _run_target_collectors(
        config,
        limit=limit,
        db_url=db_url,
        diagnostics=diagnostics,
        target_countries=["china"],
    )


def target_multiple(
    countries: list[str],
    limit: int = 50,
    db_url: str | None = None,
    diagnostics: list[str] | None = None,
) -> list["Artifact"]:
    """Toggleable multi-target. E.g. countries=['iran', 'russia'].
    All data from public sources.
    """
    artifacts: list["Artifact"] = []
    all_configs = get_all_targets()
    seen_countries = list(dict.fromkeys(country.lower() for country in countries))
    for country in seen_countries:
        config = all_configs.get(country)
        if not config:
            continue
        artifacts.extend(
            _run_target_collectors(
                config,
                limit=limit,
                db_url=db_url,
                diagnostics=diagnostics,
                target_countries=[country],
            )
        )
    return artifacts


_TARGET_STATE = target_state_file
_FALLBACK_TARGET_STATE = fallback_target_state_file


def _target_state_path() -> "Path":
    return _TARGET_STATE() if callable(_TARGET_STATE) else _TARGET_STATE


def _fallback_target_state_path() -> "Path":
    return (
        _FALLBACK_TARGET_STATE()
        if callable(_FALLBACK_TARGET_STATE)
        else _FALLBACK_TARGET_STATE
    )


def set_current_target(countries: list[str]) -> bool:
    """Persist the current target focus. Returns False when state is not writable."""
    wrote_state = False
    for state_path in (_target_state_path(), _fallback_target_state_path()):
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with state_path.open("w") as f:
                json.dump({"targets": countries or []}, f)
            wrote_state = True
        except OSError:
            continue
    return wrote_state


def get_current_target() -> list[str]:
    """Return the last set target(s), e.g. ['iran'] or [] if none."""
    state_paths = []
    for path in (_target_state_path(), _fallback_target_state_path()):
        try:
            if path.exists():
                state_paths.append((path.stat().st_mtime, path))
        except OSError:
            continue

    for _, state_path in sorted(state_paths, reverse=True):
        try:
            with state_path.open() as f:
                data = json.load(f)
            targets = data.get("targets", [])
            if isinstance(targets, list):
                return [target for target in targets if isinstance(target, str)]
            return []
        except Exception:
            continue
    return []
