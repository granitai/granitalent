"""Admin job offers router."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth import get_current_admin
from backend.database import get_db
from backend.models.db_models import JobOffer as DBJobOffer, Admin as DBAdmin
from backend.schemas.jobs import JobOfferCreate, JobOfferUpdate, BulkJobOfferRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/job-offers", tags=["Admin - Job Offers"])


@router.post("")
async def create_job_offer_endpoint(offer: JobOfferCreate, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Create a new job offer (admin)."""
    if db is None:
        db = next(get_db())

    db_job_offer = DBJobOffer(
        title=offer.title,
        description=offer.description,
        required_skills=offer.required_skills or "",
        experience_level=offer.experience_level or "",
        education_requirements=offer.education_requirements or "",
        required_languages=offer.required_languages or "",
        interview_start_language=offer.interview_start_language or "",
        interview_duration_minutes=offer.interview_duration_minutes or 20,
        custom_questions=offer.custom_questions or "",
        evaluation_weights=offer.evaluation_weights or "",
        interview_mode=offer.interview_mode or "realtime"
    )
    db.add(db_job_offer)
    db.commit()
    db.refresh(db_job_offer)

    logger.info(f"📝 Created job offer: {db_job_offer.offer_id} - {db_job_offer.title} (duration: {db_job_offer.interview_duration_minutes} min)")

    return {
        "offer_id": db_job_offer.offer_id,
        "title": db_job_offer.title,
        "description": db_job_offer.description,
        "required_skills": db_job_offer.required_skills,
        "experience_level": db_job_offer.experience_level,
        "education_requirements": db_job_offer.education_requirements,
        "required_languages": db_job_offer.required_languages,
        "interview_start_language": db_job_offer.interview_start_language,
        "interview_duration_minutes": db_job_offer.interview_duration_minutes,
        "custom_questions": db_job_offer.custom_questions,
        "evaluation_weights": db_job_offer.evaluation_weights,
        "interview_mode": db_job_offer.interview_mode,
        "created_at": db_job_offer.created_at.isoformat() if db_job_offer.created_at else None,
        "updated_at": db_job_offer.updated_at.isoformat() if db_job_offer.updated_at else None
    }


@router.get("")
async def list_job_offers(db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """List all job offers."""
    if db is None:
        db = next(get_db())

    offers = db.query(DBJobOffer).order_by(DBJobOffer.created_at.desc()).all()

    return [
        {
            "offer_id": offer.offer_id,
            "title": offer.title,
            "description": offer.description,
            "required_skills": offer.required_skills,
            "experience_level": offer.experience_level,
            "education_requirements": offer.education_requirements,
            "required_languages": offer.required_languages,
            "interview_start_language": offer.interview_start_language,
            "interview_duration_minutes": offer.interview_duration_minutes,
            "custom_questions": offer.custom_questions or "",
            "evaluation_weights": offer.evaluation_weights or "",
            "interview_mode": offer.interview_mode or "realtime",
            "created_at": offer.created_at.isoformat() if offer.created_at else None,
            "updated_at": offer.updated_at.isoformat() if offer.updated_at else None
        }
        for offer in offers
    ]


@router.get("/{offer_id}")
async def get_job_offer_endpoint(offer_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Get a specific job offer."""
    if db is None:
        db = next(get_db())

    offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Job offer not found")

    return {
        "offer_id": offer.offer_id,
        "title": offer.title,
        "description": offer.description,
        "required_skills": offer.required_skills,
        "experience_level": offer.experience_level,
        "education_requirements": offer.education_requirements,
        "required_languages": offer.required_languages,
        "interview_start_language": offer.interview_start_language,
        "interview_duration_minutes": offer.interview_duration_minutes,
        "custom_questions": offer.custom_questions or "",
        "evaluation_weights": offer.evaluation_weights or "",
        "interview_mode": offer.interview_mode or "realtime",
        "created_at": offer.created_at.isoformat() if offer.created_at else None,
        "updated_at": offer.updated_at.isoformat() if offer.updated_at else None
    }


@router.put("/{offer_id}")
async def update_job_offer_endpoint(offer_id: str, offer_update: JobOfferUpdate, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Update a job offer."""
    if db is None:
        db = next(get_db())

    offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Job offer not found")

    update_data = offer_update.dict(exclude_unset=True)
    if "title" in update_data:
        offer.title = update_data["title"]
    if "description" in update_data:
        offer.description = update_data["description"]
    if "required_skills" in update_data:
        offer.required_skills = update_data["required_skills"]
    if "experience_level" in update_data:
        offer.experience_level = update_data["experience_level"]
    if "education_requirements" in update_data:
        offer.education_requirements = update_data["education_requirements"]
    if "required_languages" in update_data:
        offer.required_languages = update_data["required_languages"]
    if "interview_start_language" in update_data:
        offer.interview_start_language = update_data["interview_start_language"]
    if "interview_duration_minutes" in update_data:
        offer.interview_duration_minutes = update_data["interview_duration_minutes"]
    if "custom_questions" in update_data:
        offer.custom_questions = update_data["custom_questions"]
    if "evaluation_weights" in update_data:
        offer.evaluation_weights = update_data["evaluation_weights"]
    if "interview_mode" in update_data:
        offer.interview_mode = update_data["interview_mode"]

    offer.updated_at = datetime.now()
    db.commit()
    db.refresh(offer)

    logger.info(f"📝 Updated job offer: {offer_id}")

    return {
        "offer_id": offer.offer_id,
        "title": offer.title,
        "description": offer.description,
        "required_skills": offer.required_skills,
        "experience_level": offer.experience_level,
        "education_requirements": offer.education_requirements,
        "required_languages": offer.required_languages,
        "interview_start_language": offer.interview_start_language,
        "interview_duration_minutes": offer.interview_duration_minutes,
        "custom_questions": offer.custom_questions or "",
        "evaluation_weights": offer.evaluation_weights or "",
        "interview_mode": offer.interview_mode or "realtime",
        "created_at": offer.created_at.isoformat() if offer.created_at else None,
        "updated_at": offer.updated_at.isoformat() if offer.updated_at else None
    }


@router.delete("/{offer_id}")
async def delete_job_offer_endpoint(offer_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Delete a job offer."""
    if db is None:
        db = next(get_db())

    offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Job offer not found")

    db.delete(offer)
    db.commit()

    logger.info(f"🗑️ Deleted job offer: {offer_id}")
    return {"message": "Job offer deleted successfully"}


@router.post("/bulk-delete")
async def bulk_delete_job_offers(body: BulkJobOfferRequest, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Permanently delete multiple job offers."""
    if not body.offer_ids:
        raise HTTPException(status_code=400, detail="No job offer IDs provided")

    deleted = db.query(DBJobOffer).filter(DBJobOffer.offer_id.in_(body.offer_ids)).delete(synchronize_session='fetch')
    db.commit()

    logger.info(f"Bulk deleted {deleted} job offers")
    return {"message": f"{deleted} job offer(s) deleted successfully", "deleted_count": deleted}
