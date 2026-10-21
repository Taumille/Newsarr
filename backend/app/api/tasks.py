"""Manual triggers for the automatic-search tasks."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.autosearch import run_auto_search, run_rss_sync

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post("/rss-sync")
async def rss_sync(db: Session = Depends(get_db)):
    """Search monitored publications for very recent issues and grab them."""
    return await run_rss_sync(db)


@router.post("/auto-search")
async def auto_search(db: Session = Depends(get_db)):
    """Thorough catch-up search for missed issues across monitored publications."""
    return await run_auto_search(db)
