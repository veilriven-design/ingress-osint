"""
Minimal media analysis.

Provides graceful degradation when exiftool/ffmpeg not present.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .models import Artifact


def _tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def download_to_temp(url: str, suffix: Optional[str] = None) -> tuple[Path, str]:
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("URL media analysis requires httpx. Install with: pip install -e '.[full]'") from exc

    with httpx.stream("GET", url, follow_redirects=True, timeout=30) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0]
        if not suffix:
            if "jpeg" in content_type or "jpg" in content_type:
                suffix = ".jpg"
            elif "png" in content_type:
                suffix = ".png"
            elif "mp4" in content_type or "video" in content_type:
                suffix = ".mp4"
            else:
                suffix = ".bin"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        path = Path(tmp.name)
        for chunk in resp.iter_bytes():
            tmp.write(chunk)
        tmp.close()
        return path, content_type


def cleanup_temp(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def extract_exif(path: Path) -> dict[str, Any]:
    if not _tool_available("exiftool"):
        return {"_warning": "exiftool not found in PATH (install for full metadata)"}
    try:
        result = subprocess.run(
            ["exiftool", "-j", "-n", str(path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list) and data:
                first = data[0]
                return first if isinstance(first, dict) else {"_warning": "exiftool returned unexpected data"}
        return {"_warning": "exiftool returned no data"}
    except Exception as e:
        return {"_error": f"exiftool failed: {e}"}


def compute_phash(path: Path) -> Optional[str]:
    try:
        import imagehash
        from PIL import Image
    except Exception:
        return None
    try:
        with Image.open(path) as img:
            work_img = img.convert("RGB") if img.mode in ("RGBA", "P") else img
            ph = imagehash.average_hash(work_img)
            return str(ph)
    except Exception:
        return None


def get_video_info(path: Path) -> dict[str, Any]:
    if not _tool_available("ffprobe"):
        return {"_warning": "ffprobe (ffmpeg) not found"}
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data if isinstance(data, dict) else {"_warning": "ffprobe returned unexpected data"}
        return {"_warning": "ffprobe returned no data"}
    except Exception as e:
        return {"_error": f"ffprobe failed: {e}"}


def extract_basic_entities(text: Optional[str], metadata: dict[str, Any]) -> list[str]:
    if not text and not metadata:
        return []
    keywords = {
        "T-72", "T-80", "T-90", "BMP", "BTR", "MT-LB", "Grad", "S-300", "S-400",
        "Su-27", "Su-35", "MiG", "IL-76", "tank", "IFV", "APC", "artillery",
        "convoy", "drone", "UAV", "Shahed", "missile", "strike", "logistics",
    }
    found: set[str] = set()
    haystack = (text or "").lower()
    for kw in keywords:
        if kw.lower() in haystack:
            found.add(kw)
    for v in list(metadata.values())[:20]:
        if isinstance(v, str):
            for kw in keywords:
                if kw.lower() in v.lower():
                    found.add(kw)
    return sorted(found)


def extract_gps_from_exif(exif: dict[str, Any]) -> Optional[tuple[float, float]]:
    try:
        lat = exif.get("GPSLatitude")
        lon = exif.get("GPSLongitude")
        lat_ref = exif.get("GPSLatitudeRef", "N")
        lon_ref = exif.get("GPSLongitudeRef", "E")
        if lat is not None and lon is not None:
            lat = float(lat)
            lon = float(lon)
            if lat_ref and str(lat_ref).upper().startswith("S"):
                lat = -lat
            if lon_ref and str(lon_ref).upper().startswith("W"):
                lon = -lon
            return lat, lon
    except Exception:
        pass
    return None


def _sha256_file(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def analyze_media(
    path: str | Path,
    *,
    is_url: bool = False,
    download: bool = True,
) -> dict[str, Any]:
    p = Path(path)
    temp_path: Optional[Path] = None
    content_type = "image" if not str(p).lower().endswith((".mp4", ".mov", ".avi")) else "video"

    try:
        if is_url and download:
            temp_path, ct = download_to_temp(str(p))
            p = temp_path
            if "video" in ct:
                content_type = "video"
            elif "image" in ct:
                content_type = "image"

        result: dict[str, Any] = {
            "path": str(p),
            "content_type": content_type,
            "size_bytes": p.stat().st_size if p.exists() else None,
            "sha256": _sha256_file(p) if p.exists() else None,
        }

        exif = extract_exif(p)
        result["exif"] = exif

        if content_type == "image":
            ph = compute_phash(p)
            result["perceptual_hash"] = ph

        if content_type == "video":
            result["video_info"] = get_video_info(p)

        text_blob = exif.get("ImageDescription") or exif.get("Caption") or ""
        entities = extract_basic_entities(text_blob, exif)
        result["entities"] = entities

        gps = extract_gps_from_exif(exif)
        if gps:
            result["gps"] = {"lat": gps[0], "lon": gps[1]}

        warnings = []
        if "_warning" in exif:
            warnings.append(exif["_warning"])
        if content_type == "image" and result.get("perceptual_hash") is None:
            warnings.append("perceptual hash unavailable (imagehash/Pillow/numpy issue or not installed)")
        if content_type == "video" and "ffprobe" in str(result.get("video_info", {})):
            warnings.append("ffprobe not available")

        if warnings:
            result["analysis_warnings"] = warnings

        return result

    finally:
        if temp_path:
            cleanup_temp(temp_path)


def make_artifact_from_analysis(
    analysis: dict[str, Any],
    source_url: Optional[str] = None,
) -> "Artifact":
    from .models import Artifact, ProvenanceEntry, Source, SourceType

    src = Source(
        id="user-media" if not source_url else "web-archive",
        name="User Media Upload" if not source_url else f"Web Archive: {source_url}",
        source_type=SourceType.USER_UPLOAD if not source_url else SourceType.WEB_ARCHIVE,
        credibility_prior=0.9 if not source_url else 0.7,
        tos_summary="User-provided or archived public media. Verify licensing and context.",
    )

    prov = ProvenanceEntry(
        source_id=src.id,
        source_type=src.source_type,
        url_or_id=source_url or str(analysis.get("path")),
        fetched_at=__import__("datetime").datetime.utcnow(),
        collector="media-analyzer",
        collector_version="0.1.0",
        tos_compliant=True,
    )

    content_hash = analysis.get("sha256")
    p = Path(analysis["path"])
    if p.exists() and not content_hash:
        try:
            content_hash = _sha256_file(p)
        except Exception:
            pass

    return Artifact(
        source=src,
        provenance=[prov],
        content_type=analysis.get("content_type", "image"),
        raw_ref=source_url,
        content_hash=content_hash,
        fetched_at=prov.fetched_at,
        text=None,
        metadata=analysis,
        media_path=str(p) if p.exists() else None,
    )
