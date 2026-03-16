"""Admin dashboard statistics routes."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_
from sqlalchemy.orm import Session

from backend.auth import get_current_admin
from backend.database import get_db
from backend.models.db_models import (
    Application as DBApplication,
    Candidate as DBCandidate,
    Interview as DBInterview,
    JobOffer as DBJobOffer,
    Admin as DBAdmin,
)

router = APIRouter(prefix="/api/admin/dashboard", tags=["Admin - Dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_admin: DBAdmin = Depends(get_current_admin)
):
    """Get dashboard statistics for admin panel."""
    if db is None:
        db = next(get_db())

    # Count applications by status
    total_applications = db.query(DBApplication).count()
    pending_applications = db.query(DBApplication).filter(DBApplication.hr_status == "pending").count()
    approved_applications = db.query(DBApplication).filter(DBApplication.ai_status == "approved").count()
    selected_applications = db.query(DBApplication).filter(DBApplication.hr_status == "selected").count()
    rejected_applications = db.query(DBApplication).filter(DBApplication.hr_status == "rejected").count()

    # Count interviews
    total_interviews = db.query(DBInterview).count()
    pending_interviews = db.query(DBInterview).filter(DBInterview.status == "pending").count()
    completed_interviews = db.query(DBInterview).filter(DBInterview.status == "completed").count()

    # Count job offers
    total_job_offers = db.query(DBJobOffer).count()
    active_job_offers = db.query(DBJobOffer).count()  # All are considered active for now

    # Count candidates
    total_candidates = db.query(DBCandidate).count()

    # Recent applications (last 7 days)
    seven_days_ago = datetime.now() - timedelta(days=7)
    recent_applications = db.query(DBApplication).filter(
        DBApplication.submitted_at >= seven_days_ago
    ).count()

    # Applications needing review (AI approved but HR pending)
    needs_review = db.query(DBApplication).filter(
        and_(
            DBApplication.ai_status == "approved",
            DBApplication.hr_status == "pending"
        )
    ).count()

    return {
        "applications": {
            "total": total_applications,
            "pending": pending_applications,
            "approved": approved_applications,
            "selected": selected_applications,
            "rejected": rejected_applications,
            "needs_review": needs_review,
            "recent": recent_applications
        },
        "interviews": {
            "total": total_interviews,
            "pending": pending_interviews,
            "completed": completed_interviews
        },
        "job_offers": {
            "total": total_job_offers,
            "active": active_job_offers
        },
        "candidates": {
            "total": total_candidates
        }
    }
