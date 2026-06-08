"""
Minimal geoparser for targeting.

In a full build this would use geotext + military location boosting.
"""

from typing import Any, Optional


def geoparse(text: str) -> list[str]:
    """Return known military-relevant place hints found in free text (Iran/Russia/China focus + theaters)."""
    if not text:
        return []
    places: list[str] = []
    text_lower = text.lower()
    # Expanded public-domain relevant locations for target countries + active theaters
    candidates = [
        "pokrovsk", "vuhledar", "kyiv", "odesa", "dnipro", "kharkiv", "belgorod", "kursk",
        "taiwan", "taiwan strait", "south china sea", "east china sea", "philippine sea",
        "hormuz", "strait of hormuz", "bandar abbas", "chabahar", "jask", "kish",
        "black sea", "crimea", "sevastopol", "zaporizhzhia", "donetsk", "luhansk",
        "hainan", "zhanjiang", "qingdao", "guangdong", "fujian", "shandong",
        "okinawa", "guam", "okinotorishima",
    ]
    for kw in candidates:
        if kw in text_lower:
            places.append(kw.title())
    # also try optional geotext if installed (broader)
    try:
        from geotext import GeoText  # type: ignore
        g = GeoText(text)
        for c in (g.cities or []):
            if len(c) > 3:
                places.append(c)
    except Exception:
        pass
    return list(dict.fromkeys(places))[:12] or []


def extract_geo_from_analysis(analysis: dict[str, Any]) -> Optional[dict[str, float]]:
    """Extract lat/lon from exif or analysis if present."""
    gps = analysis.get("gps")
    if isinstance(gps, dict) and "lat" in gps and "lon" in gps:
        return {"lat": float(gps["lat"]), "lon": float(gps["lon"])}
    exif = analysis.get("exif", {})
    if isinstance(exif, dict) and "GPSLatitude" in exif and "GPSLongitude" in exif:
        return {"lat": float(exif["GPSLatitude"]), "lon": float(exif["GPSLongitude"])}
    return None
