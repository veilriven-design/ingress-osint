"""
Core Pydantic models for Ingress: Artifact, Source, Provenance, Sighting, etc.

These provide the data contracts with full provenance tracking.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    RSS = "rss"
    TELEGRAM = "telegram"
    X = "x"
    MEDIA = "media"
    USER_UPLOAD = "user_upload"
    WEB_ARCHIVE = "web_archive"
    # Add more as collectors are added


class Source(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    source_type: SourceType
    credibility_prior: float = 0.5
    base_url: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    tos_summary: str = "Respect the source's terms of service."


class ProvenanceEntry(BaseModel):
    source_id: str
    source_type: SourceType
    url_or_id: Optional[str] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    collector: str
    collector_version: str = "0.1.0"
    content_hash: Optional[str] = None
    tos_compliant: bool = True


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source: Source
    provenance: List[ProvenanceEntry]
    content_type: str  # e.g. "text", "image", "video"
    raw_ref: Optional[str] = None
    content_hash: Optional[str] = None
    fetched_at: datetime
    text: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    media_path: Optional[str] = None


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
    artifact_ids: List[str] = Field(default_factory=list)
    timestamp: datetime
    lat: Optional[float] = None
    lon: Optional[float] = None
    location_name: Optional[str] = None
    entities: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    confidence: float = 0.5
    confidence_level: ConfidenceLevel = ConfidenceLevel.MEDIUM
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    metadata: dict[str, Any] = Field(default_factory=dict)


# Add more models as needed (e.g. Case, Note) - they are simple in cli for now.
