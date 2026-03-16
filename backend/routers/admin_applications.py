"""Admin Applications router – extracted from main.py."""

import json
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.auth import get_current_admin
from backend.database import get_db
from backend.models.db_models import (
    Application as DBApplication,
    Candidate as DBCandidate,
    CVEvaluation as DBCVEvaluation,
    Interview as DBInterview,
    JobOffer as DBJobOffer,
    Admin as DBAdmin,
)
from backend.services.storage import download_file as s3_download

# Uploads directory – mirrors main.py logic
_data_dir = os.getenv("DATA_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOADS_DIR = os.path.join(_data_dir, "uploads")

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin - Applications"])


# --------------- Pydantic request models ---------------

class OverrideRequest(BaseModel):
    hr_status: str  # "selected", "rejected"
    reason: Optional[str] = ""


class BulkApplicationRequest(BaseModel):
    application_ids: list


class BulkApplicationArchiveRequest(BaseModel):
    application_ids: list
    archive: bool = True


# --------------- Routes ---------------

@router.get("/api/admin/applications")
async def list_applications(
    job_offer_id: Optional[str] = Query(None),
    ai_status: Optional[str] = Query(None),
    hr_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="Filter applications submitted on or after this date (ISO format)"),
    date_to: Optional[str] = Query(None, description="Filter applications submitted on or before this date (ISO format)"),
    show_archived: Optional[bool] = Query(False, description="Include archived applications (default: False - show only active)"),
    db: Session = Depends(get_db),
    current_admin: DBAdmin = Depends(get_current_admin)
):
    """
    List all applications with optional filtering.

    Query params:
    - job_offer_id: Filter by job offer
    - ai_status: Filter by AI status (approved, rejected, pending)
    - hr_status: Filter by HR status (pending, selected, rejected, interview_sent)
    - search: Search by candidate name or email
    - date_from: Filter applications submitted on or after this date (ISO format, e.g., 2024-01-15)
    - date_to: Filter applications submitted on or before this date (ISO format, e.g., 2024-01-31)
    - show_archived: If true, show archived applications; if false (default), show only active
    """
    if db is None:
        db = next(get_db())

    query = db.query(DBApplication)

    # Filter by archive status (by default, show only non-archived)
    if not show_archived:
        query = query.filter(or_(DBApplication.is_archived == False, DBApplication.is_archived == None))

    # Apply filters
    if job_offer_id:
        query = query.filter(DBApplication.job_offer_id == job_offer_id)
    if ai_status:
        query = query.filter(DBApplication.ai_status == ai_status)
    if hr_status:
        query = query.filter(DBApplication.hr_status == hr_status)
    if search:
        search_filter = or_(
            DBCandidate.full_name.ilike(f"%{search}%"),
            DBCandidate.email.ilike(f"%{search}%")
        )
        query = query.join(DBCandidate).filter(search_filter)

    # Apply date filters
    if date_from:
        try:
            # Handle both date-only and datetime formats
            if 'T' in date_from:
                date_from_parsed = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            else:
                date_from_parsed = datetime.fromisoformat(date_from)
            query = query.filter(DBApplication.submitted_at >= date_from_parsed)
        except ValueError as e:
            logger.warning(f"Invalid date_from format: {date_from}, error: {e}")

    if date_to:
        try:
            # Handle both date-only and datetime formats
            if 'T' in date_to:
                date_to_parsed = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            else:
                # Add time to end of day for date-only format
                date_to_parsed = datetime.fromisoformat(date_to + "T23:59:59")
            query = query.filter(DBApplication.submitted_at <= date_to_parsed)
        except ValueError as e:
            logger.warning(f"Invalid date_to format: {date_to}, error: {e}")

    applications = query.order_by(DBApplication.submitted_at.desc()).all()

    result = []
    for app in applications:
        candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == app.candidate_id).first()
        job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == app.job_offer_id).first()

        result.append({
            "application_id": app.application_id,
            "candidate": {
                "candidate_id": candidate.candidate_id,
                "full_name": candidate.full_name,
                "email": candidate.email,
                "phone": candidate.phone,
                "linkedin": candidate.linkedin,
                "portfolio": candidate.portfolio
            },
            "job_offer": {
                "offer_id": job_offer.offer_id if job_offer else None,
                "title": job_offer.title if job_offer else "Unknown",
                "required_languages": job_offer.required_languages if job_offer else None
            },
            "cover_letter": app.cover_letter,
            "cv_filename": app.cv_filename,
            "ai_status": app.ai_status,
            "ai_reasoning": app.ai_reasoning,
            "ai_score": app.ai_score,
            "hr_status": app.hr_status,
            "hr_override_reason": app.hr_override_reason,
            "interview_invited_at": app.interview_invited_at.isoformat() if app.interview_invited_at else None,
            "interview_completed_at": app.interview_completed_at.isoformat() if app.interview_completed_at else None,
            "interview_recommendation": app.interview_recommendation,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
            "is_archived": app.is_archived or False,
            "archived_at": app.archived_at.isoformat() if app.archived_at else None
        })

    return result


@router.get("/api/admin/applications/search")
async def search_applications(
    q: Optional[str] = Query(None),
    job_offer_id: Optional[str] = Query(None),
    ai_status: Optional[str] = Query(None),
    hr_status: Optional[str] = Query(None),
    current_admin: DBAdmin = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """
    Search and filter applications.
    Combines all filter options.
    """
    if db is None:
        db = next(get_db())

    query = db.query(DBApplication)

    # Apply filters
    if job_offer_id:
        query = query.filter(DBApplication.job_offer_id == job_offer_id)
    if ai_status:
        query = query.filter(DBApplication.ai_status == ai_status)
    if hr_status:
        query = query.filter(DBApplication.hr_status == hr_status)
    if q:
        # Search in candidate name, email, or cover letter
        search_filter = or_(
            DBCandidate.full_name.ilike(f"%{q}%"),
            DBCandidate.email.ilike(f"%{q}%"),
            DBApplication.cover_letter.ilike(f"%{q}%")
        )
        query = query.join(DBCandidate).filter(search_filter)

    applications = query.order_by(DBApplication.submitted_at.desc()).all()

    result = []
    for app in applications:
        candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == app.candidate_id).first()
        job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == app.job_offer_id).first()

        result.append({
            "application_id": app.application_id,
            "candidate_name": candidate.full_name,
            "candidate_email": candidate.email,
            "job_title": job_offer.title if job_offer else "Unknown",
            "ai_status": app.ai_status,
            "hr_status": app.hr_status,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None
        })

    return {"results": result, "count": len(result)}


@router.get("/api/admin/applications/{application_id}/cv-file")
async def download_cv_file(application_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Download the original CV PDF file for admin preview."""
    application = db.query(DBApplication).filter(DBApplication.application_id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    cv_path = getattr(application, 'cv_file_path', None)
    if not cv_path:
        raise HTTPException(status_code=404, detail="CV file not available for this application")
    file_bytes = s3_download(cv_path, local_dir=UPLOADS_DIR)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="CV file not found")
    filename = application.cv_filename or f"{application_id}.pdf"
    return Response(
        content=file_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )


@router.get("/api/admin/applications/{application_id}")
async def get_application_details(application_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Get full application details including CV text."""
    if db is None:
        db = next(get_db())

    application = db.query(DBApplication).filter(DBApplication.application_id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == application.candidate_id).first()
    job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == application.job_offer_id).first()

    # Get interview records
    interviews = db.query(DBInterview).filter(DBInterview.application_id == application_id).all()

    return {
        "application_id": application.application_id,
        "candidate": {
            "candidate_id": candidate.candidate_id,
            "full_name": candidate.full_name,
            "email": candidate.email,
            "phone": candidate.phone,
            "linkedin": candidate.linkedin,
            "portfolio": candidate.portfolio
        },
        "job_offer": {
            "offer_id": job_offer.offer_id if job_offer else None,
            "title": job_offer.title if job_offer else "Unknown",
            "description": job_offer.description if job_offer else "",
            "required_languages": job_offer.required_languages if job_offer else None
        },
        "cover_letter": application.cover_letter,
        "cv_text": application.cv_text,
        "cv_filename": application.cv_filename,
        "cv_file_available": bool(getattr(application, 'cv_file_path', None)),
        "ai_status": application.ai_status,
        "ai_reasoning": application.ai_reasoning,
        "ai_score": application.ai_score,
        "ai_skills_match": application.ai_skills_match,
        "ai_experience_match": application.ai_experience_match,
        "ai_education_match": application.ai_education_match,
        "language_check": json.loads(application.language_check_json) if application.language_check_json else None,
        "job_fit_check": json.loads(application.job_fit_check_json) if application.job_fit_check_json else None,
        "hr_status": application.hr_status,
        "hr_override_reason": application.hr_override_reason,
        "interview_invited_at": application.interview_invited_at.isoformat() if application.interview_invited_at else None,
        "interview_completed_at": application.interview_completed_at.isoformat() if application.interview_completed_at else None,
        "interview_assessment": application.interview_assessment,
        "interview_recommendation": application.interview_recommendation,
        "submitted_at": application.submitted_at.isoformat() if application.submitted_at else None,
        "interviews": [
            {
                "interview_id": interview.interview_id,
                "status": interview.status,
                "recommendation": interview.recommendation,
                "assessment": interview.assessment,
                "conversation_history": interview.conversation_history,
                "has_recording": interview.recording_audio is not None,
                "created_at": interview.created_at.isoformat() if interview.created_at else None,
                "completed_at": interview.completed_at.isoformat() if interview.completed_at else None
            }
            for interview in interviews
        ]
    }


@router.get("/api/admin/job-offers/{offer_id}/applications")
async def get_job_offer_applications(offer_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Get all applications for a specific job offer with AI pre-selection status."""
    if db is None:
        db = next(get_db())

    # Verify job offer exists
    job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == offer_id).first()
    if not job_offer:
        raise HTTPException(status_code=404, detail="Job offer not found")

    applications = db.query(DBApplication).filter(DBApplication.job_offer_id == offer_id).all()

    # Separate by AI status
    approved = []
    rejected = []
    pending = []

    for app in applications:
        candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == app.candidate_id).first()

        app_data = {
            "application_id": app.application_id,
            "candidate": {
                "candidate_id": candidate.candidate_id,
                "full_name": candidate.full_name,
                "email": candidate.email,
                "phone": candidate.phone
            },
            "ai_status": app.ai_status,
            "ai_reasoning": app.ai_reasoning,
            "ai_score": app.ai_score,
            "hr_status": app.hr_status,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None
        }

        if app.ai_status == "approved":
            approved.append(app_data)
        elif app.ai_status == "rejected":
            rejected.append(app_data)
        else:
            pending.append(app_data)

    return {
        "job_offer": {
            "offer_id": job_offer.offer_id,
            "title": job_offer.title
        },
        "approved": approved,
        "rejected": rejected,
        "pending": pending,
        "total": len(applications)
    }


@router.post("/api/admin/applications/{application_id}/override")
async def override_ai_decision(application_id: str, override: OverrideRequest, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """
    Allow HR to override AI decision.
    If AI rejected but HR wants to select, or vice versa.
    """
    if db is None:
        db = next(get_db())

    application = db.query(DBApplication).filter(DBApplication.application_id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    if override.hr_status not in ["selected", "rejected"]:
        raise HTTPException(status_code=400, detail="hr_status must be 'selected' or 'rejected'")

    # Update HR status
    application.hr_status = override.hr_status
    application.hr_override_reason = override.reason or ""
    application.updated_at = datetime.now()

    db.commit()
    db.refresh(application)

    logger.info(f"🔄 HR override: Application {application_id} - AI: {application.ai_status}, HR: {override.hr_status}")

    return {
        "application_id": application_id,
        "ai_status": application.ai_status,
        "hr_status": application.hr_status,
        "hr_override_reason": application.hr_override_reason,
        "message": "AI decision overridden successfully"
    }


@router.post("/api/admin/applications/{application_id}/select")
async def select_candidate(application_id: str, reason: Optional[str] = Query(None), db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Mark candidate as selected by HR (can override AI rejection)."""
    if db is None:
        db = next(get_db())

    application = db.query(DBApplication).filter(DBApplication.application_id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    application.hr_status = "selected"
    if reason:
        application.hr_override_reason = reason
    application.updated_at = datetime.now()

    db.commit()

    return {"message": "Candidate selected successfully", "hr_status": "selected"}


@router.post("/api/admin/applications/{application_id}/reject")
async def reject_candidate(application_id: str, reason: Optional[str] = Query(None), db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Mark candidate as rejected by HR."""
    if db is None:
        db = next(get_db())

    application = db.query(DBApplication).filter(DBApplication.application_id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    application.hr_status = "rejected"
    if reason:
        application.hr_override_reason = reason
    application.updated_at = datetime.now()

    db.commit()

    return {"message": "Candidate rejected", "hr_status": "rejected"}


@router.post("/api/admin/applications/{application_id}/archive")
async def archive_application(application_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Archive an application (soft delete - hidden from main view but not deleted)."""
    if db is None:
        db = next(get_db())

    application = db.query(DBApplication).filter(DBApplication.application_id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    application.is_archived = True
    application.archived_at = datetime.now()
    application.updated_at = datetime.now()

    db.commit()

    logger.info(f"📦 Application archived: {application_id}")
    return {"message": "Application archived successfully", "is_archived": True}


@router.post("/api/admin/applications/{application_id}/unarchive")
async def unarchive_application(application_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Restore an archived application back to active view."""
    if db is None:
        db = next(get_db())

    application = db.query(DBApplication).filter(DBApplication.application_id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    application.is_archived = False
    application.archived_at = None
    application.updated_at = datetime.now()

    db.commit()

    logger.info(f"📤 Application unarchived: {application_id}")
    return {"message": "Application restored successfully", "is_archived": False}


@router.delete("/api/admin/applications/{application_id}")
async def delete_application(application_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Permanently delete an application and its related interviews."""
    if db is None:
        db = next(get_db())

    application = db.query(DBApplication).filter(DBApplication.application_id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    # Delete related interviews first
    db.query(DBInterview).filter(DBInterview.application_id == application_id).delete()
    # Delete related CV evaluations
    db.query(DBCVEvaluation).filter(DBCVEvaluation.application_id == application_id).delete()
    # Delete the application
    db.delete(application)
    db.commit()

    logger.info(f"🗑️ Application permanently deleted: {application_id}")
    return {"message": "Application deleted successfully"}


@router.post("/api/admin/applications/bulk-delete")
async def bulk_delete_applications(body: BulkApplicationRequest, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Permanently delete multiple applications and their related data."""
    if not body.application_ids:
        raise HTTPException(status_code=400, detail="No application IDs provided")

    # Delete related interviews and CV evaluations first
    db.query(DBInterview).filter(DBInterview.application_id.in_(body.application_ids)).delete(synchronize_session='fetch')
    db.query(DBCVEvaluation).filter(DBCVEvaluation.application_id.in_(body.application_ids)).delete(synchronize_session='fetch')
    deleted = db.query(DBApplication).filter(DBApplication.application_id.in_(body.application_ids)).delete(synchronize_session='fetch')
    db.commit()

    logger.info(f"Bulk deleted {deleted} applications")
    return {"message": f"{deleted} application(s) deleted successfully", "deleted_count": deleted}


@router.post("/api/admin/applications/bulk-archive")
async def bulk_archive_applications(body: BulkApplicationArchiveRequest, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Archive or unarchive multiple applications at once."""
    if not body.application_ids:
        raise HTTPException(status_code=400, detail="No application IDs provided")

    applications = db.query(DBApplication).filter(DBApplication.application_id.in_(body.application_ids)).all()
    for application in applications:
        application.is_archived = body.archive
        application.archived_at = datetime.utcnow() if body.archive else None
    db.commit()

    action = "archived" if body.archive else "restored"
    logger.info(f"Bulk {action} {len(applications)} applications")
    return {"message": f"{len(applications)} application(s) {action} successfully", "count": len(applications)}
