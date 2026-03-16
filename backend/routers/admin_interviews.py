"""Admin interview management routes."""
import base64
import json
import logging
import threading

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.auth import get_current_admin
from backend.database import get_db, SessionLocal
from backend.models.db_models import (
    JobOffer as DBJobOffer,
    Candidate as DBCandidate,
    Application as DBApplication,
    Interview as DBInterview,
    Admin as DBAdmin,
)
from backend.services.storage import download_file as s3_download
from backend.state import UPLOADS_DIR
from backend.utils import extract_detailed_scores, extract_recommendation

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin - Interviews"])


# ---- Request models ----

class InterviewInvitationRequest(BaseModel):
    interview_date: Optional[str] = None  # ISO format date string
    notes: Optional[str] = ""


class BulkInterviewRequest(BaseModel):
    interview_ids: list


class BulkArchiveRequest(BaseModel):
    interview_ids: list
    archive: bool = True


# ---- Routes ----

@router.post("/api/admin/applications/{application_id}/send-interview")
async def send_interview_invitation(
    application_id: str,
    invitation: InterviewInvitationRequest,
    db: Session = Depends(get_db),
    current_admin: DBAdmin = Depends(get_current_admin)
):
    """
    Send interview invitation to candidate.
    For now, just updates status and stores invitation data.
    Email integration will be added later.
    """
    if db is None:
        db = next(get_db())

    application = db.query(DBApplication).filter(DBApplication.application_id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    # Update application status
    application.hr_status = "interview_sent"
    application.interview_invited_at = datetime.now()
    application.updated_at = datetime.now()
    db.commit()  # Commit application update first

    # Get candidate and job offer
    logger.info(f"🔍 Looking for candidate with ID: {application.candidate_id}")
    candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == application.candidate_id).first()

    if candidate is None:
        logger.error(f"❌ Candidate not found for application {application_id}, candidate_id: {application.candidate_id}")
        raise HTTPException(status_code=404, detail="Candidate not found")

    logger.info(f"✅ Found candidate: {candidate.full_name} (ID: {candidate.candidate_id}, Email: {candidate.email})")

    # Ensure full_name exists
    candidate_name = candidate.full_name if candidate.full_name else "Unknown Candidate"
    if not candidate.full_name:
        logger.warning(f"⚠️ Candidate {candidate.candidate_id} has no full_name, using default")

    job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == application.job_offer_id).first()
    if not job_offer:
        logger.error(f"❌ Job offer not found for application {application_id}, job_offer_id: {application.job_offer_id}")
        raise HTTPException(status_code=404, detail="Job offer not found")

    # Create interview record (allow multiple interviews per application)
    # Check if there are existing completed interviews, but still allow creating new ones
    existing_interviews = db.query(DBInterview).filter(DBInterview.application_id == application_id).all()
    completed_count = sum(1 for i in existing_interviews if i.status == "completed")

    try:
        interview = DBInterview(
            application_id=application_id,
            job_offer_id=application.job_offer_id,
            status="pending",
            candidate_name=candidate_name
        )
        db.add(interview)
        db.commit()
        db.refresh(interview)
        logger.info(f"✅ Interview record created: {interview.interview_id} (Attempt #{len(existing_interviews) + 1}, {completed_count} previous completed)")
    except Exception as e:
        logger.error(f"❌ Error creating interview record: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating interview record: {str(e)}")

    logger.info(f"📧 Interview invitation sent: {application_id} for {job_offer.title} to {candidate.email}")

    return {
        "interview_id": interview.interview_id,
        "application_id": application_id,
        "status": "interview_sent",
        "interview_invited_at": application.interview_invited_at.isoformat(),
        "interview_date": invitation.interview_date,
        "notes": invitation.notes,
        "message": "Interview invitation sent (email integration pending)"
    }


@router.get("/api/admin/interviews")
async def list_interviews(
    status: Optional[str] = Query(None),
    job_offer_id: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="Filter interviews created on or after this date (ISO format)"),
    date_to: Optional[str] = Query(None, description="Filter interviews created on or before this date (ISO format)"),
    show_archived: Optional[bool] = Query(False, description="Include archived interviews (default: False - show only active)"),
    db: Session = Depends(get_db),
    current_admin: DBAdmin = Depends(get_current_admin)
):
    """
    List all interview invitations and their status.

    Query params:
    - status: Filter by interview status (pending, completed, cancelled)
    - job_offer_id: Filter by job offer
    - date_from: Filter interviews created on or after this date (ISO format, e.g., 2024-01-15)
    - date_to: Filter interviews created on or before this date (ISO format, e.g., 2024-01-31)
    - show_archived: If true, show archived interviews; if false (default), show only active
    """
    if db is None:
        db = next(get_db())

    query = db.query(DBInterview)

    # Filter by archive status (by default, show only non-archived)
    if not show_archived:
        query = query.filter(or_(DBInterview.is_archived == False, DBInterview.is_archived == None))

    if status:
        query = query.filter(DBInterview.status == status)
    if job_offer_id:
        query = query.filter(DBInterview.job_offer_id == job_offer_id)

    # Apply date filters
    if date_from:
        try:
            if 'T' in date_from:
                date_from_parsed = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            else:
                date_from_parsed = datetime.fromisoformat(date_from)
            query = query.filter(DBInterview.created_at >= date_from_parsed)
        except ValueError as e:
            logger.warning(f"Invalid date_from format: {date_from}, error: {e}")

    if date_to:
        try:
            if 'T' in date_to:
                date_to_parsed = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            else:
                date_to_parsed = datetime.fromisoformat(date_to + "T23:59:59")
            query = query.filter(DBInterview.created_at <= date_to_parsed)
        except ValueError as e:
            logger.warning(f"Invalid date_to format: {date_to}, error: {e}")

    interviews = query.order_by(DBInterview.created_at.desc()).all()

    result = []
    for interview in interviews:
        application = db.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first() if interview.application_id else None
        candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == application.candidate_id).first() if application else None
        job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == interview.job_offer_id).first()

        result.append({
            "interview_id": interview.interview_id,
            "application_id": interview.application_id,
            "candidate": {
                "name": candidate.full_name if candidate else interview.candidate_name,
                "email": candidate.email if candidate else None
            },
            "job_offer": {
                "offer_id": job_offer.offer_id if job_offer else None,
                "title": job_offer.title if job_offer else "Unknown"
            },
            "status": interview.status,
            "recommendation": interview.recommendation,
            "created_at": interview.created_at.isoformat() if interview.created_at else None,
            "completed_at": interview.completed_at.isoformat() if interview.completed_at else None,
            "is_archived": interview.is_archived or False,
            "archived_at": interview.archived_at.isoformat() if interview.archived_at else None
        })

    return result


@router.get("/api/admin/interviews/{interview_id}")
async def get_interview_details(interview_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Get interview details including assessment if completed."""
    if db is None:
        db = next(get_db())

    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    application = db.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first() if interview.application_id else None
    candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == application.candidate_id).first() if application else None
    job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == interview.job_offer_id).first()

    return {
        "interview_id": interview.interview_id,
        "application_id": interview.application_id,
        "candidate": {
            "name": candidate.full_name if candidate else interview.candidate_name,
            "email": candidate.email if candidate else None
        },
        "job_offer": {
            "offer_id": job_offer.offer_id if job_offer else None,
            "title": job_offer.title if job_offer else "Unknown"
        },
        "status": interview.status,
        "recommendation": interview.recommendation,
        "assessment": interview.assessment,
        "evaluation_scores": json.loads(interview.evaluation_scores) if interview.evaluation_scores else None,
        "conversation_history": interview.conversation_history,
        "has_recording": interview.recording_audio is not None,
        "has_video": interview.recording_video is not None,
        "recording_video": interview.recording_video,
        "audio_segments": json.loads(interview.audio_segments) if hasattr(interview, 'audio_segments') and interview.audio_segments else [],
        "created_at": interview.created_at.isoformat() if interview.created_at else None,
        "completed_at": interview.completed_at.isoformat() if interview.completed_at else None
    }


@router.post("/api/admin/interviews/{interview_id}/regenerate-assessment")
async def regenerate_interview_assessment(interview_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Regenerate the assessment for a completed interview (e.g., after API quota is reloaded)."""
    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    if not interview.conversation_history:
        raise HTTPException(status_code=400, detail="No conversation history available to generate assessment")

    history = json.loads(interview.conversation_history)
    if len(history) < 2:
        raise HTTPException(status_code=400, detail="Conversation too short to generate assessment")

    # Build context from available data
    ctx = {}
    if interview.application_id:
        app = db.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first()
        if app:
            ctx["candidate_cv_text"] = app.cv_text[:3000] if app.cv_text else ""
            ctx["confirmed_candidate_name"] = interview.candidate_name
            job = db.query(DBJobOffer).filter(DBJobOffer.offer_id == interview.job_offer_id).first()
            if job:
                ctx["job_title"] = job.title

    # Run in background thread to not block the request
    def _regen_bg():
        try:
            db_bg = SessionLocal()
            try:
                from backend.services.openai_llm import generate_assessment as gen_assess
                assessment = gen_assess(history, interview_context=ctx)
                recommendation = extract_recommendation(assessment)
                detailed_scores = extract_detailed_scores(assessment)

                iv = db_bg.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
                if iv:
                    iv.assessment = assessment
                    iv.recommendation = recommendation
                    iv.evaluation_scores = json.dumps(detailed_scores)

                    if iv.application_id:
                        app_rec = db_bg.query(DBApplication).filter(
                            DBApplication.application_id == iv.application_id
                        ).first()
                        if app_rec:
                            app_rec.interview_assessment = assessment
                            app_rec.interview_recommendation = recommendation
                            app_rec.updated_at = datetime.now()

                    db_bg.commit()
                    logger.info(f"✅ Assessment regenerated for interview {interview_id}")

                    # Also regenerate transcript annotations
                    try:
                        feedback_lang = None
                        if iv.application_id:
                            app_check = db_bg.query(DBApplication).filter(
                                DBApplication.application_id == iv.application_id
                            ).first()
                            if app_check and app_check.required_languages:
                                langs = json.loads(app_check.required_languages)
                                feedback_lang = langs[0] if langs else None
                        from backend.services.language_llm_openai import generate_transcript_annotations as gem_ann
                        annotations = gem_ann(conversation_history=history, feedback_language=feedback_lang)
                        hist_copy = json.loads(iv.conversation_history)
                        for i, msg in enumerate(hist_copy):
                            if msg["role"] == "user":
                                idx_str = str(i)
                                if idx_str in annotations:
                                    msg["ai_comment"] = annotations[idx_str]
                        iv.conversation_history = json.dumps(hist_copy)
                        db_bg.commit()
                    except Exception as ann_err:
                        logger.error(f"Transcript annotation regen failed: {ann_err}")
            except Exception as e:
                logger.error(f"❌ Assessment regeneration failed: {e}")
                db_bg.rollback()
            finally:
                db_bg.close()
        except Exception as e:
            logger.error(f"❌ Assessment regeneration thread error: {e}")

    threading.Thread(target=_regen_bg, daemon=True).start()
    return {"message": "Assessment regeneration started. It will be available shortly."}


@router.get("/api/admin/interviews/{interview_id}/recording")
async def get_interview_recording(interview_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Get the interview recording audio file."""
    if db is None:
        db = next(get_db())

    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    if not interview.recording_audio:
        raise HTTPException(status_code=404, detail="No recording available for this interview")

    # Determine audio format from the stored key/data
    audio_key = interview.recording_audio
    if audio_key.startswith("s3://"):
        audio_key = audio_key[5:]

    # If it looks like a file path/key (not raw base64), fetch from storage
    if "/" in audio_key or audio_key.endswith((".wav", ".mp3", ".webm")):
        audio_bytes = s3_download(audio_key, local_dir=UPLOADS_DIR)
        if not audio_bytes:
            raise HTTPException(status_code=404, detail="Recording file not found")
        audio_format = "wav" if audio_key.endswith(".wav") else "mp3"
        return {
            "interview_id": interview_id,
            "recording_audio": base64.b64encode(audio_bytes).decode('utf-8'),
            "audio_format": audio_format
        }

    return {
        "interview_id": interview_id,
        "recording_audio": interview.recording_audio,
        "audio_format": "mp3"
    }


@router.get("/api/admin/interviews/{interview_id}/turn-audio/{audio_key:path}")
async def get_interview_turn_audio(interview_id: str, audio_key: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Serve a per-turn candidate audio WAV file."""
    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    audio_bytes = s3_download(audio_key, local_dir=UPLOADS_DIR)
    if not audio_bytes:
        raise HTTPException(status_code=404, detail="Turn audio not found")
    return Response(content=audio_bytes, media_type="audio/wav")


@router.get("/api/admin/interviews/{interview_id}/video")
async def get_interview_video(interview_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Get the interview video recording or snapshot metadata."""
    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview or not interview.recording_video:
        raise HTTPException(status_code=404, detail="No video recording available")

    # Check if it's snapshot metadata (JSON)
    try:
        meta = json.loads(interview.recording_video)
        if meta.get("type") == "snapshots":
            return JSONResponse(content=meta)
    except (json.JSONDecodeError, TypeError):
        pass

    # Legacy: serve video file
    video_bytes = s3_download(interview.recording_video, local_dir=UPLOADS_DIR)
    if not video_bytes:
        raise HTTPException(status_code=404, detail="Video file not found")
    ext = interview.recording_video.rsplit('.', 1)[-1] if '.' in interview.recording_video else "webm"
    return Response(content=video_bytes, media_type=f"video/{ext}")


@router.get("/api/admin/interviews/{interview_id}/snapshots/{index}")
async def get_interview_snapshot(interview_id: str, index: int, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Get a specific snapshot image."""
    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview or not interview.recording_video:
        raise HTTPException(status_code=404, detail="No snapshots available")
    try:
        meta = json.loads(interview.recording_video)
        if meta.get("type") != "snapshots":
            raise HTTPException(status_code=404, detail="No snapshots for this interview")
        snaps = meta.get("snapshots", [])
        if index < 0 or index >= len(snaps):
            raise HTTPException(status_code=404, detail="Snapshot index out of range")
        snap_key = snaps[index]["key"]
        img_bytes = s3_download(snap_key, local_dir=UPLOADS_DIR)
        if not img_bytes:
            raise HTTPException(status_code=404, detail="Snapshot file not found")
        return Response(content=img_bytes, media_type="image/jpeg")
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=404, detail="Invalid snapshot data")


@router.post("/api/admin/interviews/{interview_id}/archive")
async def archive_interview(interview_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Archive an interview (soft delete - hidden from main view but not deleted)."""
    if db is None:
        db = next(get_db())

    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    interview.is_archived = True
    interview.archived_at = datetime.now()

    db.commit()

    logger.info(f"📦 Interview archived: {interview_id}")
    return {"message": "Interview archived successfully", "is_archived": True}


@router.post("/api/admin/interviews/{interview_id}/unarchive")
async def unarchive_interview(interview_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Restore an archived interview back to active view."""
    if db is None:
        db = next(get_db())

    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    interview.is_archived = False
    interview.archived_at = None

    db.commit()

    logger.info(f"📤 Interview unarchived: {interview_id}")
    return {"message": "Interview restored successfully", "is_archived": False}


@router.delete("/api/admin/interviews/{interview_id}")
async def delete_interview(interview_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Permanently delete an interview."""
    if db is None:
        db = next(get_db())

    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    db.delete(interview)
    db.commit()

    logger.info(f"🗑️ Interview permanently deleted: {interview_id}")
    return {"message": "Interview deleted successfully"}


@router.post("/api/admin/interviews/bulk-delete")
async def bulk_delete_interviews(body: BulkInterviewRequest, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Permanently delete multiple interviews at once."""
    if not body.interview_ids:
        raise HTTPException(status_code=400, detail="No interview IDs provided")

    deleted = db.query(DBInterview).filter(DBInterview.interview_id.in_(body.interview_ids)).delete(synchronize_session='fetch')
    db.commit()

    logger.info(f"Bulk deleted {deleted} interviews")
    return {"message": f"{deleted} interview(s) deleted successfully", "deleted_count": deleted}


@router.post("/api/admin/interviews/bulk-archive")
async def bulk_archive_interviews(body: BulkArchiveRequest, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Archive or unarchive multiple interviews at once."""
    if not body.interview_ids:
        raise HTTPException(status_code=400, detail="No interview IDs provided")

    interviews = db.query(DBInterview).filter(DBInterview.interview_id.in_(body.interview_ids)).all()
    for interview in interviews:
        interview.is_archived = body.archive
        interview.archived_at = datetime.utcnow() if body.archive else None
    db.commit()

    action = "archived" if body.archive else "restored"
    logger.info(f"Bulk {action} {len(interviews)} interviews")
    return {"message": f"{len(interviews)} interview(s) {action} successfully", "count": len(interviews)}
