"""Ad-hoc release search across Prowlarr."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import SearchResponse
from ..services import settings as settings_service
from ..services.clients import prowlarr_from_settings
from ..services.prowlarr import ProwlarrError
from ..services.search import parse_categories

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def search(
    query: str = Query(min_length=1),
    categories: str = Query(default=""),
    db: Session = Depends(get_db),
):
    cfg = settings_service.get_map(db)
    try:
        client = prowlarr_from_settings(cfg)
        releases = await client.search(query, categories=parse_categories(categories))
    except ProwlarrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SearchResponse(query=query, releases=releases)
