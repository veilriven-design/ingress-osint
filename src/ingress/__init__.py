"""
Ingress — Open-source military OSINT megatool / suite.

High-integrity platform for detecting, verifying, fusing, and analyzing
military-relevant information as it enters the open (public) domains.

Core principles (from the project charter):
- Simple, delightful UX over extremely careful & auditable internals.
- Always reviewable/auditable output with full provenance.
- Data/observation-driven (real signals → structured insight).
- Safety, minimality, air-gap / offline friendly by design.
- Legal & ethical hygiene first-class and per-source.
- Targeted collection (API-first, scoped, rate-limited).
- Incremental, reviewable, high-quality engineering.

Country-specific targeting (toggleable, real data only):
- target_iran(), target_russia(), target_china(), target_multiple([...])
- Separate functions per country.
- CLI: ingress ingest target --iran --russia --china (any combination)
- All sources/keywords from REAL public open military OSINT (official media, Rybar, PLA Daily, Tasnim, etc.).
- Results automatically available in real-data TUI (watch), storage, delta, cases, GeoJSON export, etc.

This is alpha software. Use responsibly and in accordance with all
applicable laws and source Terms of Service.
"""

__version__ = "0.1.0"

from .targeting import (
    get_iran_config,
    get_russia_config,
    get_china_config,
    get_target_config,
    target_iran,
    target_russia,
    target_china,
    target_multiple,
)

__all__ = [
    "__version__",
    "get_iran_config",
    "get_russia_config",
    "get_china_config",
    "get_target_config",
    "target_iran",
    "target_russia",
    "target_china",
    "target_multiple",
]