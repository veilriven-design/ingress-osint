"""
Minimal geoparser for targeting.

In a full build this would use geotext + military location boosting.
"""

from typing import Any, Optional


def geoparse(text: str) -> list[str]:
    """Return known military-relevant place hints found in free text."""
    if not text:
        return []
    # Dummy: look for common military places mentioned in keywords
    places = []
    text_lower = text.lower()
    for kw in ["pokrovsk", "vuhledar", "kyiv", "odesa", "taiwan", "hormuz", "black sea", "south china sea"]:
        if kw in text_lower:
            places.append(kw.title())
    return list(set(places)) or []


def extract_geo_from_analysis(analysis: dict[str, Any]) -> Optional[dict[str, float]]:
    """Extract lat/lon from exif or analysis if present."""
    gps = analysis.get("gps")
    if isinstance(gps, dict) and "lat" in gps and "lon" in gps:
        return {"lat": float(gps["lat"]), "lon": float(gps["lon"])}
    exif = analysis.get("exif", {})
    if isinstance(exif, dict) and "GPSLatitude" in exif and "GPSLongitude" in exif:
        return {"lat": float(exif["GPSLatitude"]), "lon": float(exif["GPSLongitude"])}
    return None
