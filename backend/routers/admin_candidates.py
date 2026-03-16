"""Admin candidate management routes."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.auth import get_current_admin
from backend.database import get_db
from backend.models.db_models import (
    Candidate as DBCandidate,
    Application as DBApplication,
    CVEvaluation as DBCVEvaluation,
    Interview as DBInterview,
    JobOffer as DBJobOffer,
    Admin as DBAdmin,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/candidates", tags=["Admin - Candidates"])


class BulkCandidateRequest(BaseModel):
    candidate_ids: list


@router.get("/search")
async def search_candidates(
    q: Optional[str] = Query(None),
    skills: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Search candidates by name, email, or skills (in CV text).
    """
    if db is None:
        db = next(get_db())

    query = db.query(DBCandidate)

    if q:
        query = query.filter(
            or_(
                DBCandidate.full_name.ilike(f"%{q}%"),
                DBCandidate.email.ilike(f"%{q}%")
            )
        )

    candidates = query.all()

    result = []
    for candidate in candidates:
        # If skills filter, check in applications' CV text
        if skills:
            applications = db.query(DBApplication).filter(DBApplication.candidate_id == candidate.candidate_id).all()
            has_skills = any(skills.lower() in app.cv_text.lower() for app in applications)
            if not has_skills:
                continue

        applications = db.query(DBApplication).filter(DBApplication.candidate_id == candidate.candidate_id).all()

        result.append({
            "candidate_id": candidate.candidate_id,
            "full_name": candidate.full_name,
            "email": candidate.email,
            "phone": candidate.phone,
            "total_applications": len(applications),
            "latest_application": applications[0].submitted_at.isoformat() if applications else None
        })

    return {"results": result, "count": len(result)}


@router.get("")
async def list_candidates(
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_admin: DBAdmin = Depends(get_current_admin)
):
    """
    List all candidates (archive).

    Query params:
    - search: Search by name or email
    - status: Filter by application status (optional)
    """
    if db is None:
        db = next(get_db())

    query = db.query(DBCandidate)

    if search:
        query = query.filter(
            or_(
                DBCandidate.full_name.ilike(f"%{search}%"),
                DBCandidate.email.ilike(f"%{search}%")
            )
        )

    candidates = query.order_by(DBCandidate.created_at.desc()).all()

    result = []
    for candidate in candidates:
        # Get all applications for this candidate
        applications = db.query(DBApplication).filter(DBApplication.candidate_id == candidate.candidate_id).all()

        # Filter by status if provided
        if status:
            applications = [app for app in applications if app.hr_status == status or app.ai_status == status]

        result.append({
            "candidate_id": candidate.candidate_id,
            "full_name": candidate.full_name,
            "email": candidate.email,
            "phone": candidate.phone,
            "linkedin": candidate.linkedin,
            "portfolio": candidate.portfolio,
            "total_applications": len(applications),
            "latest_application": applications[0].submitted_at.isoformat() if applications else None,
            "created_at": candidate.created_at.isoformat() if candidate.created_at else None
        })

    return result


@router.get("/{candidate_email}")
async def get_candidate_by_email(candidate_email: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Get all applications from a specific candidate (by email)."""
    if db is None:
        db = next(get_db())

    candidate = db.query(DBCandidate).filter(DBCandidate.email == candidate_email).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    applications = db.query(DBApplication).filter(DBApplication.candidate_id == candidate.candidate_id).all()

    result_applications = []
    for app in applications:
        job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == app.job_offer_id).first()

        result_applications.append({
            "application_id": app.application_id,
            "job_offer": {
                "offer_id": job_offer.offer_id if job_offer else None,
                "title": job_offer.title if job_offer else "Unknown"
            },
            "cover_letter": app.cover_letter,
            "cv_text": app.cv_text,
            "cv_filename": app.cv_filename,
            "ai_status": app.ai_status,
            "ai_reasoning": app.ai_reasoning,
            "ai_score": app.ai_score,
            "hr_status": app.hr_status,
            "interview_invited_at": app.interview_invited_at.isoformat() if app.interview_invited_at else None,
            "interview_completed_at": app.interview_completed_at.isoformat() if app.interview_completed_at else None,
            "interview_recommendation": app.interview_recommendation,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None
        })

    return {
        "candidate": {
            "candidate_id": candidate.candidate_id,
            "full_name": candidate.full_name,
            "email": candidate.email,
            "phone": candidate.phone,
            "linkedin": candidate.linkedin,
            "portfolio": candidate.portfolio,
            "created_at": candidate.created_at.isoformat() if candidate.created_at else None
        },
        "applications": result_applications
    }


@router.post("/bulk-delete")
async def bulk_delete_candidates(body: BulkCandidateRequest, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Permanently delete multiple candidates and all their related data."""
    if not body.candidate_ids:
        raise HTTPException(status_code=400, detail="No candidate IDs provided")

    # Get all applications for these candidates
    app_ids = [a.application_id for a in db.query(DBApplication).filter(DBApplication.candidate_id.in_(body.candidate_ids)).all()]
    if app_ids:
        db.query(DBInterview).filter(DBInterview.application_id.in_(app_ids)).delete(synchronize_session='fetch')
        db.query(DBCVEvaluation).filter(DBCVEvaluation.application_id.in_(app_ids)).delete(synchronize_session='fetch')
        db.query(DBApplication).filter(DBApplication.application_id.in_(app_ids)).delete(synchronize_session='fetch')

    deleted = db.query(DBCandidate).filter(DBCandidate.candidate_id.in_(body.candidate_ids)).delete(synchronize_session='fetch')
    db.commit()

    logger.info(f"Bulk deleted {deleted} candidates")
    return {"message": f"{deleted} candidate(s) deleted successfully", "deleted_count": deleted}


@router.delete("/{candidate_id}")
async def delete_candidate(candidate_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Permanently delete a candidate and all their applications and interviews."""
    if db is None:
        db = next(get_db())

    candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Delete related interviews and CV evaluations for all applications
    applications = db.query(DBApplication).filter(DBApplication.candidate_id == candidate_id).all()
    for app in applications:
        db.query(DBInterview).filter(DBInterview.application_id == app.application_id).delete()
        db.query(DBCVEvaluation).filter(DBCVEvaluation.application_id == app.application_id).delete()

    # Delete all applications
    db.query(DBApplication).filter(DBApplication.candidate_id == candidate_id).delete()
    # Delete the candidate
    db.delete(candidate)
    db.commit()

    logger.info(f"Candidate permanently deleted: {candidate_id}")
    return {"message": "Candidate and all related data deleted successfully"}
