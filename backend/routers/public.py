"""Public / candidate-facing routes — applications, job listings, interviews."""

import logging
import os
import threading
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.config import DEFAULT_LLM_PROVIDER
from backend.database import get_db
from backend.models.db_models import (
    JobOffer as DBJobOffer,
    Candidate as DBCandidate,
    Application as DBApplication,
    Interview as DBInterview,
)
from backend.services.cv_parser import parse_pdf, validate_pdf
from backend.services.storage import upload_file as s3_upload
from backend.state import candidate_applications, UPLOADS_DIR

# Import the background helper from the cv router
from backend.routers.cv import _run_cv_evaluation_background

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Public"])


# ------------------------------------------------------------------
# Candidate application endpoints
# ------------------------------------------------------------------

@router.post("/candidates/apply")
async def submit_application(
    job_offer_id: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    linkedin: Optional[str] = Form(""),
    portfolio: Optional[str] = Form(""),
    cover_letter_file: Optional[UploadFile] = File(None),
    cv_file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Submit a candidate application for a job offer.
    CV is uploaded immediately and evaluation runs in the background.
    """
    try:
        # Validate job offer exists in database
        db_job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == job_offer_id).first()
        if not db_job_offer:
            raise HTTPException(status_code=404, detail="Job offer not found")

        from backend.models.job_offer import JobOffer
        job_offer = JobOffer(
            title=db_job_offer.title,
            description=db_job_offer.description,
            required_skills=db_job_offer.required_skills or "",
            experience_level=db_job_offer.experience_level or "",
            education_requirements=db_job_offer.education_requirements or "",
            offer_id=db_job_offer.offer_id
        )

        # Validate PDF
        file_content = await cv_file.read()
        if not validate_pdf(file_content):
            raise HTTPException(status_code=400, detail="Invalid PDF file")

        # Parse CV text
        cv_text = parse_pdf(file_content)

        # Generate application ID and save the PDF file
        application_id = f"app_{uuid.uuid4().hex[:12]}"
        cv_relative_path = f"cvs/{application_id}.pdf"
        s3_upload(file_content, cv_relative_path, content_type="application/pdf", local_dir=UPLOADS_DIR)

        # Handle cover letter file if provided
        cover_letter_text = ""
        cover_letter_filename = None
        if cover_letter_file:
            cover_letter_filename = cover_letter_file.filename
            cover_letter_content = await cover_letter_file.read()
            if cover_letter_filename.lower().endswith('.pdf'):
                try:
                    cover_letter_text = parse_pdf(cover_letter_content)
                except:
                    cover_letter_text = ""

        # Get or create candidate
        candidate = db.query(DBCandidate).filter(DBCandidate.email == email).first()
        if not candidate:
            candidate = DBCandidate(
                email=email,
                full_name=full_name,
                phone=phone,
                linkedin=linkedin or None,
                portfolio=portfolio or None
            )
            db.add(candidate)
            db.flush()

        # Create application immediately with "processing" status
        application = DBApplication(
            application_id=application_id,
            candidate_id=candidate.candidate_id,
            job_offer_id=job_offer_id,
            cover_letter=cover_letter_text or "",
            cover_letter_filename=cover_letter_filename,
            cv_text=cv_text,
            cv_filename=cv_file.filename,
            cv_file_path=cv_relative_path,
            ai_status="processing",
            ai_reasoning="CV evaluation in progress...",
            hr_status="pending"
        )
        db.add(application)
        db.commit()

        logger.info(f"Application submitted: {application_id} for {job_offer.title} by {full_name}")

        # Run CV evaluation in the background
        eval_thread = threading.Thread(
            target=_run_cv_evaluation_background,
            args=(application_id, cv_text, job_offer.get_full_description(), db_job_offer.required_languages, job_offer_id),
            daemon=True
        )
        eval_thread.start()

        return {
            "application_id": application_id,
            "status": "submitted",
            "message": "Your application has been submitted successfully! Our team will review your CV shortly."
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing application: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error processing application: {str(e)}")


@router.get("/candidates/applications/{application_id}")
async def get_application(application_id: str):
    """Get a candidate application by ID."""
    if application_id not in candidate_applications:
        raise HTTPException(status_code=404, detail="Application not found")

    application = candidate_applications[application_id].copy()
    # Don't return full CV text in public endpoint
    application.pop("cv_text", None)
    return application


# ------------------------------------------------------------------
# Public job listings
# ------------------------------------------------------------------

@router.get("/job-offers")
async def get_public_job_offers(db: Session = Depends(get_db)):
    """Get all job offers (public endpoint for candidate selection)."""
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
            "created_at": offer.created_at.isoformat() if offer.created_at else None,
            "updated_at": offer.updated_at.isoformat() if offer.updated_at else None
        }
        for offer in offers
    ]


# ------------------------------------------------------------------
# Candidate self-service: applications & interviews by email
# ------------------------------------------------------------------

@router.get("/candidates/applications")
async def get_candidate_applications(
    email: str = Query(..., description="Candidate email address"),
    db: Session = Depends(get_db)
):
    """Get all applications for a candidate by email."""
    if db is None:
        db = next(get_db())

    # Normalize email: trim whitespace and convert to lowercase for comparison
    email_normalized = email.strip().lower()

    logger.info(f"Searching for applications for email: {email_normalized}")

    # Use case-insensitive email comparison
    candidate = db.query(DBCandidate).filter(func.lower(DBCandidate.email) == email_normalized).first()
    if not candidate:
        logger.warning(f"Candidate not found for email: {email_normalized}")
        # Return empty list instead of 404 - candidate might not exist yet
        return []

    logger.info(f"Found candidate: {candidate.full_name} (ID: {candidate.candidate_id})")

    # Get all applications for this candidate
    applications = db.query(DBApplication).filter(DBApplication.candidate_id == candidate.candidate_id).order_by(DBApplication.submitted_at.desc()).all()
    logger.info(f"Found {len(applications)} applications for candidate")

    if not applications:
        return []

    result = []
    for app in applications:
        job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == app.job_offer_id).first()

        # Check if there's an interview for this application
        interview = db.query(DBInterview).filter(DBInterview.application_id == app.application_id).first()

        # Map AI status to a more generic status for candidates
        # Don't expose AI evaluation details to candidates
        # Use HR status if available, otherwise show "under_review" if AI has evaluated
        if app.hr_status == "selected":
            status = "selected"
        elif app.hr_status == "rejected":
            status = "rejected"
        elif app.hr_status == "interview_sent":
            status = "interview_sent"
        elif app.hr_status == "pending" and app.ai_status in ["approved", "rejected"]:
            status = "under_review"
        elif app.hr_status:
            status = app.hr_status
        else:
            status = "pending"

        result.append({
            "application_id": app.application_id,
            "job_offer": {
                "offer_id": job_offer.offer_id if job_offer else None,
                "title": job_offer.title if job_offer else "Unknown",
                "description": job_offer.description if job_offer else ""
            },
            "status": status,  # Generic status, not AI-specific
            "hr_status": app.hr_status,
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
            "interview_invited_at": app.interview_invited_at.isoformat() if app.interview_invited_at else None,
            "interview_completed_at": app.interview_completed_at.isoformat() if app.interview_completed_at else None,
            "interview_recommendation": app.interview_recommendation,
            "has_interview": interview is not None,
            "interview_id": interview.interview_id if interview else None,
            "interview_status": interview.status if interview else None
        })

    return result


@router.get("/candidates/interviews")
async def get_candidate_interviews(
    email: str = Query(..., description="Candidate email address"),
    db: Session = Depends(get_db)
):
    """Get all interviews for a candidate by email."""
    if db is None:
        db = next(get_db())

    # Normalize email: trim whitespace and convert to lowercase for comparison
    email_normalized = email.strip().lower()

    logger.info(f"Searching for interviews for email: {email_normalized}")

    # Use case-insensitive email comparison
    candidate = db.query(DBCandidate).filter(func.lower(DBCandidate.email) == email_normalized).first()
    if not candidate:
        logger.warning(f"Candidate not found for email: {email_normalized}")
        # Return empty list instead of 404 - candidate might not exist yet
        return []

    logger.info(f"Found candidate: {candidate.full_name} (ID: {candidate.candidate_id})")

    # Get all applications for this candidate
    applications = db.query(DBApplication).filter(DBApplication.candidate_id == candidate.candidate_id).all()
    logger.info(f"Found {len(applications)} applications for candidate")

    if not applications:
        return []

    application_ids = [app.application_id for app in applications]
    logger.info(f"Application IDs: {application_ids}")

    # Get all interviews for these applications
    interviews = db.query(DBInterview).filter(DBInterview.application_id.in_(application_ids)).all()
    logger.info(f"Found {len(interviews)} interviews for applications")

    if not interviews:
        return []

    result = []
    for interview in interviews:
        application = db.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first()
        job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == interview.job_offer_id).first()

        result.append({
            "interview_id": interview.interview_id,
            "application_id": interview.application_id,
            "job_offer": {
                "offer_id": job_offer.offer_id if job_offer else None,
                "title": job_offer.title if job_offer else "Unknown",
                "interview_mode": job_offer.interview_mode if job_offer else "realtime"
            },
            "status": interview.status,
            "recommendation": interview.recommendation,
            "created_at": interview.created_at.isoformat() if interview.created_at else None,
            "completed_at": interview.completed_at.isoformat() if interview.completed_at else None,
            "interview_invited_at": application.interview_invited_at.isoformat() if application and application.interview_invited_at else None
        })

    return result


@router.get("/candidates/interviews/{interview_id}")
async def get_candidate_interview_details(
    interview_id: str,
    email: str = Query(..., description="Candidate email address for verification"),
    db: Session = Depends(get_db)
):
    """Get interview details for a candidate (with email verification)."""
    if db is None:
        db = next(get_db())

    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    application = db.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == application.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Verify email matches
    if candidate.email != email:
        raise HTTPException(status_code=403, detail="Access denied. Email does not match interview candidate.")

    job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == interview.job_offer_id).first()

    return {
        "interview_id": interview.interview_id,
        "application_id": interview.application_id,
        "job_offer": {
            "offer_id": job_offer.offer_id if job_offer else None,
            "title": job_offer.title if job_offer else "Unknown",
            "description": job_offer.description if job_offer else "",
            "interview_mode": job_offer.interview_mode if job_offer else "realtime"
        },
        "status": interview.status,
        "recommendation": interview.recommendation,
        "assessment": interview.assessment,
        "conversation_history": interview.conversation_history,
        "cv_text": application.cv_text,  # Include CV text for interview context
        "created_at": interview.created_at.isoformat() if interview.created_at else None,
        "completed_at": interview.completed_at.isoformat() if interview.completed_at else None,
        "interview_invited_at": application.interview_invited_at.isoformat() if application and application.interview_invited_at else None
    }
