"""
Core Pydantic models for Ingress: Artifact, Source, Provenance, Sighting, etc.

These provide the data contracts with full provenance tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    RSS = "rss"
    TELEGRAM = "telegram"
    X = "x"
    MEDIA = "media"
    USER_UPLOAD = "user_upload"
    WEB_ARCHIVE = "web_archive"
    WEB_PAGE = "web_page"
    # Add more as collectors are added


class Source(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    source_type: SourceType
    credibility_prior: float = 0.5
    base_url: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    tos_summary: str = "Respect the source's terms of service."


class ProvenanceEntry(BaseModel):
    source_id: str
    source_type: SourceType
    url_or_id: str | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    collector: str
    collector_version: str = "0.1.0"
    content_hash: str | None = None
    tos_compliant: bool = True


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source: Source
    provenance: list[ProvenanceEntry]
    content_type: str  # e.g. "text", "image", "video"
    raw_ref: str | None = None
    content_hash: str | None = None
    fetched_at: datetime
    text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    media_path: str | None = None


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    ANALYST_REVIEWED = "analyst_reviewed"
    CORROBORATED = "corroborated"
    VISUALLY_CONFIRMED = "visually_confirmed"


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Sighting(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    artifact_ids: list[str] = Field(default_factory=list)
    timestamp: datetime
    lat: float | None = None
    lon: float | None = None
    location_name: str | None = None
    entities: list[str] = Field(default_factory=list)
    description: str | None = None
    confidence: float = 0.5
    confidence_level: ConfidenceLevel = ConfidenceLevel.MEDIUM
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    metadata: dict[str, Any] = Field(default_factory=dict)


# Add more models as needed (e.g. Case, Note) - they are simple in cli for now.
