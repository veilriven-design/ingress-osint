"""
Minimal FastAPI surface for Ingress.

The API exposes the same SQLite-backed artifacts and sightings used by the CLI.
It is intentionally small: collection still happens through explicit CLI commands
so public-source access remains reviewable and operator-driven.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import __version__
from .config import get_db_url
from .storage import ensure_schema, get_recent_artifacts, get_sightings


class IngestRequest(BaseModel):
    source_type: str = Field(..., examples=["rss"])
    url: str | None = Field(None, examples=["https://example.com/feed.xml"])


def create_app() -> FastAPI:
    app = FastAPI(
        title="Ingress",
        version=__version__,
        summary="High-integrity OSINT signals as they enter open domains.",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/artifacts")
    def artifacts(
        limit: int = Query(30, ge=1, le=500),
        db_url: str | None = Query(None),
    ) -> list[dict[str, Any]]:
        url = db_url or get_db_url()
        try:
            ensure_schema(url)
            return get_recent_artifacts(limit, url)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/sightings")
    def sightings(
        limit: int = Query(1000, ge=1, le=5000),
        db_url: str | None = Query(None),
    ) -> list[dict[str, Any]]:
        url = db_url or get_db_url()
        try:
            ensure_schema(url)
            return get_sightings(limit, url)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/ingest")
    def ingest(request: IngestRequest) -> dict[str, str | None]:
        if request.source_type != "rss":
            raise HTTPException(
                status_code=400,
                detail="Only rss ingest is planned for the API skeleton. Use the CLI for collectors.",
            )
        return {
            "status": "not_started",
            "source_type": request.source_type,
            "url": request.url,
            "next_step": "Run `ingress ingest rss <url>` to keep collection auditable.",
        }

    return app


app = create_app()
