"""Issue catalog API: list, generate, scan, mark and search individual issues."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Issue, IssueStatus, Publication
from ..schemas import (
    DownloadRecordSchema,
    GrabRequest,
    Issue as IssueSchema,
    IssueListResponse,
    IssueSearchMissingRequest,
    IssueUpdate,
    SearchResponse,
)
from ..services.grab import GrabError, grab_release
from ..services.issues import (
    pick_most_seeded,
    scan_library,
    search_for_issue,
    search_missing,
    summary_for,
    sync_calendar,
)
from ..services.prowlarr import ProwlarrError

router = APIRouter(prefix="/api/v1", tags=["issues"])


def _get_publication(db: Session, publication_id: int) -> Publication:
    publication = db.get(Publication, publication_id)
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    return publication


def _get_issue(db: Session, issue_id: int) -> Issue:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


def _filters(publication_id: int, status: str | None, from_date: date | None, to_date: date | None):
    conditions = [Issue.publication_id == publication_id]
    status = (status or "").strip().lower()
    if status == "missing":
        conditions += [Issue.status == IssueStatus.expected, Issue.issue_date <= date.today()]
    elif status == "upcoming":
        conditions += [Issue.status == IssueStatus.expected, Issue.issue_date > date.today()]
    elif status in {s.value for s in IssueStatus}:
        conditions.append(Issue.status == IssueStatus(status))
    if from_date is not None:
        conditions.append(Issue.issue_date >= from_date)
    if to_date is not None:
        conditions.append(Issue.issue_date <= to_date)
    return conditions


@router.get(
    "/publications/{publication_id}/issues", response_model=IssueListResponse
)
def list_issues(
    publication_id: int,
    status: str | None = Query(default=None),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    _get_publication(db, publication_id)
    conditions = _filters(publication_id, status, from_date, to_date)

    total = db.execute(select(func.count(Issue.id)).where(*conditions)).scalar_one()
    issues = (
        db.execute(
            select(Issue)
            .where(*conditions)
            .order_by(Issue.issue_date.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return IssueListResponse(
        issues=[IssueSchema.model_validate(issue) for issue in issues],
        summary=summary_for(db, publication_id),
        total=int(total),
        offset=offset,
        limit=limit,
    )


@router.post("/publications/{publication_id}/issues/generate")
def generate_issues(publication_id: int, db: Session = Depends(get_db)):
    publication = _get_publication(db, publication_id)
    if not publication.start_date:
        raise HTTPException(
            status_code=400,
            detail="Set a start date and a frequency on the publication first",
        )
    result = sync_calendar(db, publication)
    return {"ok": True, **result, "summary": summary_for(db, publication_id)}


@router.post("/publications/{publication_id}/issues/scan")
def scan_issues(publication_id: int, db: Session = Depends(get_db)):
    publication = _get_publication(db, publication_id)
    result = scan_library(db, publication)
    return {"ok": True, **result, "summary": summary_for(db, publication_id)}


@router.post("/publications/{publication_id}/issues/search-missing")
async def search_missing_issues(
    publication_id: int,
    payload: IssueSearchMissingRequest | None = None,
    db: Session = Depends(get_db),
):
    publication = _get_publication(db, publication_id)
    max_grabs = payload.max_grabs if payload else 10
    try:
        result = await search_missing(db, publication, max_grabs=max_grabs)
    except ProwlarrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, **result, "summary": summary_for(db, publication_id)}


@router.get("/issues/{issue_id}", response_model=IssueSchema)
def get_issue(issue_id: int, db: Session = Depends(get_db)):
    return _get_issue(db, issue_id)


@router.patch("/issues/{issue_id}", response_model=IssueSchema)
def update_issue(issue_id: int, payload: IssueUpdate, db: Session = Depends(get_db)):
    issue = _get_issue(db, issue_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("status") is not None:
        issue.status = data["status"]
        if issue.status in (IssueStatus.expected, IssueStatus.ignored):
            issue.download_id = None
        if issue.status == IssueStatus.expected:
            issue.file_path = ""
    if data.get("label") is not None:
        issue.label = data["label"]
    if data.get("notes") is not None:
        issue.notes = data["notes"]
    if data.get("file_path") is not None:
        issue.file_path = data["file_path"]
    db.commit()
    db.refresh(issue)
    return issue


@router.post("/issues/{issue_id}/search", response_model=SearchResponse)
async def search_issue(issue_id: int, db: Session = Depends(get_db)):
    issue = _get_issue(db, issue_id)
    publication = _get_publication(db, issue.publication_id)
    try:
        releases = await search_for_issue(db, publication, issue)
    except ProwlarrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    query = f"{publication.title} {issue.issue_date.isoformat()}"
    return SearchResponse(query=query, releases=releases)


@router.post("/issues/{issue_id}/grab", response_model=DownloadRecordSchema)
async def grab_issue(
    issue_id: int, payload: GrabRequest, db: Session = Depends(get_db)
):
    issue = _get_issue(db, issue_id)
    try:
        record = await grab_release(
            db, payload.release, issue.publication_id, issue_id=issue.id
        )
    except GrabError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return record


@router.post("/issues/{issue_id}/auto-grab", response_model=DownloadRecordSchema)
async def auto_grab_issue(issue_id: int, db: Session = Depends(get_db)):
    """Search for one issue and grab the matching release with the most seeders."""
    issue = _get_issue(db, issue_id)
    if issue.status != IssueStatus.expected:
        raise HTTPException(
            status_code=409,
            detail="Only missing or upcoming issues can be auto-downloaded",
        )
    publication = _get_publication(db, issue.publication_id)

    try:
        releases = await search_for_issue(db, publication, issue)
    except ProwlarrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    candidate = pick_most_seeded(releases)
    if candidate is None:
        raise HTTPException(
            status_code=404,
            detail=f"No dated release found for {issue.issue_date.isoformat()}",
        )

    try:
        return await grab_release(
            db, candidate, issue.publication_id, issue_id=issue.id
        )
    except GrabError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
