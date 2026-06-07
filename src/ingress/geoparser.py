"""
Minimal geoparser for targeting.

In a full build this would use geotext + military location boosting.
"""

from typing import List, Optional, Dict, Any


def geoparse(text: str) -> List[str]:
    """Very basic placeholder geoparser. Returns empty or dummy locations."""
    if not text:
        return []
    # Dummy: look for common military places mentioned in keywords
    places = []
    text_lower = text.lower()
    for kw in ["pokrovsk", "vuhledar", "kyiv", "odesa", "taiwan", "hormuz", "black sea", "south china sea"]:
        if kw in text_lower:
            places.append(kw.title())
    return list(set(places)) or []


def extract_geo_from_analysis(analysis: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Extract lat/lon from exif or analysis if present."""
    if analysis.get("gps"):
        return analysis["gps"]
    exif = analysis.get("exif", {})
    if "GPSLatitude" in exif and "GPSLongitude" in exif:
        return {"lat": float(exif["GPSLatitude"]), "lon": float(exif["GPSLongitude"])}
    return None
