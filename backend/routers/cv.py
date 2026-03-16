"""CV management routes — upload, evaluate, and retrieve CV evaluations."""

import json
import logging
import uuid
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from sqlalchemy.orm import Session

from backend.config import DEFAULT_LLM_PROVIDER
from backend.database import SessionLocal, get_db
from backend.models.db_models import (
    JobOffer as DBJobOffer,
    Application as DBApplication,
    CVEvaluation as DBCVEvaluation,
)
from backend.services.cv_parser import parse_pdf, validate_pdf
from backend.services.language_evaluator import evaluate_cv_fit
from backend.state import cv_evaluations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cv", tags=["CV Management"])


# ------------------------------------------------------------------
# Helper — background CV evaluation
# ------------------------------------------------------------------

def _run_cv_evaluation_background(application_id: str, cv_text: str, job_description: str, required_languages: str, job_offer_id: str):
    """Run CV evaluation in a background thread and update the database."""
    from backend.database import SessionLocal
    try:
        logger.info(f"Background CV evaluation started for {application_id}")
        evaluation_result = evaluate_cv_fit(
            cv_text=cv_text,
            job_offer_description=job_description,
            llm_provider=DEFAULT_LLM_PROVIDER,
            required_languages=required_languages
        )

        bg_db = SessionLocal()
        try:
            app_record = bg_db.query(DBApplication).filter(DBApplication.application_id == application_id).first()
            if app_record:
                app_record.ai_status = evaluation_result["status"]
                app_record.ai_reasoning = evaluation_result.get("reasoning", "")
                app_record.ai_score = evaluation_result.get("score", 0)
                app_record.ai_skills_match = evaluation_result.get("skills_match", 0)
                app_record.ai_experience_match = evaluation_result.get("experience_match", 0)
                app_record.ai_education_match = evaluation_result.get("education_match", 0)
                app_record.language_check_json = json.dumps(evaluation_result.get("language_check")) if evaluation_result.get("language_check") else None
                app_record.job_fit_check_json = json.dumps(evaluation_result.get("job_fit_check")) if evaluation_result.get("job_fit_check") else None

            cv_eval = DBCVEvaluation(
                evaluation_id=f"eval_{uuid.uuid4().hex[:12]}",
                application_id=application_id,
                job_offer_id=job_offer_id,
                status=evaluation_result["status"],
                score=evaluation_result.get("score", 0),
                skills_match=evaluation_result.get("skills_match", 0),
                experience_match=evaluation_result.get("experience_match", 0),
                education_match=evaluation_result.get("education_match", 0),
                reasoning=evaluation_result.get("reasoning", ""),
                cv_text_length=len(cv_text),
                parsed_cv_text=cv_text
            )
            bg_db.add(cv_eval)
            bg_db.commit()
            logger.info(f"Background CV evaluation completed for {application_id}: {evaluation_result['status']}")
        finally:
            bg_db.close()
    except Exception as e:
        logger.error(f"Background CV evaluation failed for {application_id}: {e}")
        # Mark as error so admin knows evaluation failed
        try:
            bg_db = SessionLocal()
            app_record = bg_db.query(DBApplication).filter(DBApplication.application_id == application_id).first()
            if app_record and app_record.ai_status == "processing":
                app_record.ai_status = "error"
                app_record.ai_reasoning = f"Evaluation failed: {str(e)}"
                bg_db.commit()
            bg_db.close()
        except Exception:
            pass


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@router.post("/upload")
async def upload_cv(
    file: UploadFile = File(...),
    job_offer_id: str = Form(...),
    llm_provider: Optional[str] = Form(None),
    llm_model: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Upload and evaluate a CV against a job offer.

    Returns:
        Evaluation result with status (approved/rejected) and reasoning
    """
    try:
        # Read file content
        file_content = await file.read()

        # Validate PDF
        if not validate_pdf(file_content):
            raise HTTPException(status_code=400, detail="Invalid PDF file")

        # Parse PDF
        cv_text = parse_pdf(file_content)

        # Get job offer from database
        db_job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == job_offer_id).first()
        if not db_job_offer:
            raise HTTPException(status_code=404, detail="Job offer not found")

        # Create JobOffer object for compatibility
        from backend.models.job_offer import JobOffer
        job_offer = JobOffer(
            title=db_job_offer.title,
            description=db_job_offer.description,
            required_skills=db_job_offer.required_skills or "",
            experience_level=db_job_offer.experience_level or "",
            education_requirements=db_job_offer.education_requirements or "",
            offer_id=db_job_offer.offer_id
        )

        # Evaluate CV - Language evaluator checks if CV has required languages
        evaluation_result = evaluate_cv_fit(
            cv_text=cv_text,
            job_offer_description=job_offer.get_full_description(),
            llm_provider=llm_provider or DEFAULT_LLM_PROVIDER,
            llm_model=llm_model,
            required_languages=db_job_offer.required_languages
        )

        # Store evaluation (including parsed CV text for debugging)
        evaluation_id = f"eval_{uuid.uuid4().hex[:12]}"
        evaluation_data = {
            "evaluation_id": evaluation_id,
            "job_offer_id": job_offer_id,
            "status": evaluation_result["status"],
            "score": evaluation_result.get("score", 0),
            "skills_match": evaluation_result.get("skills_match", 0),
            "experience_match": evaluation_result.get("experience_match", 0),
            "education_match": evaluation_result.get("education_match", 0),
            "reasoning": evaluation_result.get("reasoning", ""),
            "cv_text_length": len(cv_text),
            "parsed_cv_text": cv_text  # Store full parsed text for debugging
        }
        cv_evaluations[evaluation_id] = evaluation_data

        # Log parsed CV content for debugging
        logger.info(f"Parsed CV content ({len(cv_text)} chars):\n{cv_text[:1000]}...")

        logger.info(f"CV evaluation complete: {evaluation_id} - {evaluation_result['status']}")

        return evaluation_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing CV: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing CV: {str(e)}")


@router.get("/evaluation/{evaluation_id}")
async def get_evaluation(evaluation_id: str, include_cv_text: bool = False):
    """
    Get CV evaluation result by ID.

    Args:
        evaluation_id: The evaluation ID
        include_cv_text: If True, includes the full parsed CV text (default: False)
    """
    if evaluation_id not in cv_evaluations:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    evaluation = cv_evaluations[evaluation_id].copy()

    # Only include parsed CV text if explicitly requested (for debugging)
    if not include_cv_text:
        evaluation.pop("parsed_cv_text", None)

    return evaluation


@router.get("/evaluation/{evaluation_id}/parsed-text")
async def get_parsed_cv_text(evaluation_id: str):
    """Get the parsed CV text for a specific evaluation (debug endpoint)."""
    if evaluation_id not in cv_evaluations:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    evaluation = cv_evaluations[evaluation_id]
    parsed_text = evaluation.get("parsed_cv_text", "")

    if not parsed_text:
        raise HTTPException(status_code=404, detail="Parsed CV text not found for this evaluation")

    return {
        "evaluation_id": evaluation_id,
        "parsed_cv_text": parsed_text,
        "text_length": len(parsed_text)
    }
