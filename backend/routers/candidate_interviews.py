"""Candidate async interview router — public endpoints (no admin auth)."""
import asyncio
import base64
import json
import logging
import re
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, WebSocket
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import (
    DEFAULT_TTS_PROVIDER, DEFAULT_STT_PROVIDER, DEFAULT_LLM_PROVIDER,
    TTS_PROVIDERS, STT_PROVIDERS, LLM_PROVIDERS,
    INTERVIEW_TIME_LIMIT_MINUTES,
    build_interviewer_system_prompt,
)
from backend.database import get_db, SessionLocal
from backend.models.conversation import ConversationManager
from backend.models.db_models import (
    JobOffer as DBJobOffer,
    Candidate as DBCandidate,
    Application as DBApplication,
    CVEvaluation as DBCVEvaluation,
    Interview as DBInterview,
)
from backend.services.storage import upload_file as s3_upload, download_file as s3_download, is_s3_enabled
from backend.state import (
    active_conversations,
    session_configs,
    interview_start_times,
    cv_evaluations,
    UPLOADS_DIR, VIDEOS_DIR, CVS_DIR,
    CONCLUSION_PHRASES,
)
from backend.utils import (
    get_llm_functions,
    get_tts_function,
    get_stt_function,
    get_voice_id,
    _retry_on_quota,
    extract_detailed_scores,
    extract_recommendation,
    get_language_code,
    cleanup_dedup_cache,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/candidates/interviews", tags=["Candidate - Interviews"])


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class AsyncInterviewStartRequest(BaseModel):
    interview_id: str
    email: str
    tts_provider: str = "elevenlabs"
    tts_model: str = ""
    stt_provider: str = "elevenlabs"
    stt_model: str = ""
    llm_provider: str = "gemini"
    llm_model: str = ""


class AsyncInterviewAnswerRequest(BaseModel):
    interview_id: str
    email: str
    audio: str  # Base64 encoded audio
    question_number: int


class AsyncInterviewRecordingRequest(BaseModel):
    interview_id: str
    email: str
    user_audio: str  # Base64 encoded user audio (continuous recording)
    ai_audio_chunks: list  # List of AI audio chunks with timestamps: [{"audio": base64, "format": "mp3", "timestamp": ms}]


class SnapshotUploadRequest(BaseModel):
    email: str
    snapshots: list  # [{timestamp: str, image: str (base64 JPEG)}]


class AsyncInterviewEndRequest(BaseModel):
    interview_id: str
    email: str


# ---------------------------------------------------------------------------
# check_and_handle_time_limit — used by WebSocket real-time interview handler
# ---------------------------------------------------------------------------

async def check_and_handle_time_limit(
    conversation_id: str,
    websocket: WebSocket,
    active_conversations: dict,
    session_configs: dict,
    interview_start_times: dict
) -> bool:
    """
    Check if interview time limit has been exceeded and end interview if so.

    Returns:
        True if interview should continue, False if it was ended due to time limit
    """
    if conversation_id not in interview_start_times:
        return True  # No time tracking, continue

    start_time = interview_start_times[conversation_id]
    elapsed_minutes = (time.time() - start_time) / 60

    # Get the interview duration from config (defaults to global limit)
    config = session_configs.get(conversation_id, {})
    time_limit = config.get("interview_duration_minutes", INTERVIEW_TIME_LIMIT_MINUTES)

    if elapsed_minutes >= time_limit:
        logger.info(f"⏰ Time limit reached for {conversation_id}: {elapsed_minutes:.2f} minutes >= {time_limit} minutes")

        # Get conversation and config
        if conversation_id not in active_conversations:
            return False

        conv = active_conversations[conversation_id]
        history = conv.get_history_for_llm()
        interview_context = conv.get_interview_context()
        config = session_configs.get(conversation_id, {})

        # Only generate assessment if we're in the actual interview phase
        current_phase = conv.get_current_phase()
        is_interview_phase = current_phase == ConversationManager.PHASE_INTERVIEW

        # Generate assessment if in interview phase
        if is_interview_phase and len(history) >= 2:
            logger.info(f"📊 Generating assessment for time-limited interview")
            llm_funcs = get_llm_functions(config.get("llm_provider", DEFAULT_LLM_PROVIDER))

            try:
                assessment = llm_funcs["generate_assessment"](
                    history,
                    model_id=config.get("llm_model", LLM_PROVIDERS[config.get("llm_provider", DEFAULT_LLM_PROVIDER)]["default_model"]),
                    interview_context=interview_context
                )

                # Store assessment in database (same logic as end_interview)
                try:
                    db = next(get_db())

                    recommendation = extract_recommendation(assessment)
                    detailed_scores = extract_detailed_scores(assessment)

                    application_id = config.get("application_id")
                    if not application_id:
                        evaluation_id = config.get("evaluation_id")
                        if evaluation_id:
                            if evaluation_id in cv_evaluations:
                                application_id = cv_evaluations[evaluation_id].get("application_id")
                            if not application_id:
                                cv_eval = db.query(DBCVEvaluation).filter(
                                    DBCVEvaluation.evaluation_id == evaluation_id
                                ).first()
                                if cv_eval:
                                    application_id = cv_eval.application_id

                    job_offer_id = config.get("job_offer_id")
                    candidate_name = conv.get_candidate_name() or config.get("candidate_name")
                    cv_text = config.get("candidate_cv_text", "")

                    interview = None
                    if application_id:
                        interview = db.query(DBInterview).filter(
                            DBInterview.application_id == application_id
                        ).order_by(DBInterview.created_at.desc()).first()

                    if not interview:
                        interview = DBInterview(
                            application_id=application_id,
                            job_offer_id=job_offer_id or "",
                            candidate_name=candidate_name,
                            cv_text=cv_text[:5000] if cv_text else None,
                            status="completed",
                            assessment=assessment,
                            recommendation=recommendation,
                            evaluation_scores=json.dumps(detailed_scores),
                            conversation_history=json.dumps(history),
                            completed_at=datetime.now()
                        )
                        db.add(interview)
                    else:
                        interview.status = "completed"
                        interview.assessment = assessment
                        interview.recommendation = recommendation
                        interview.evaluation_scores = json.dumps(detailed_scores)
                        interview.conversation_history = json.dumps(history)
                        interview.completed_at = datetime.now()

                    if application_id:
                        application = db.query(DBApplication).filter(
                            DBApplication.application_id == application_id
                        ).first()
                        if application:
                            application.interview_completed_at = datetime.now()
                            application.interview_assessment = assessment
                            application.interview_recommendation = recommendation
                            application.updated_at = datetime.now()

                    db.commit()
                    logger.info(f"✅ Time-limited interview assessment stored: interview_id={interview.interview_id}")

                    # Generate transcript annotations (AI feedback per user message)
                    try:
                        llm_provider_tl = config.get("llm_provider", DEFAULT_LLM_PROVIDER)
                        llm_model_tl = config.get("llm_model", LLM_PROVIDERS[llm_provider_tl]["default_model"])
                        _tl_ann_lang = conv.interview_start_language if conv else None
                        if llm_provider_tl == "gpt" or llm_provider_tl == "openai":
                            from backend.services.language_llm_openai import generate_transcript_annotations as gemini_generate_transcript_annotations
                            annotations = gemini_generate_transcript_annotations(conversation_history=history, model_id=llm_model_tl, feedback_language=_tl_ann_lang)
                        else:
                            from backend.services.language_llm_openai import generate_transcript_annotations as gemini_generate_transcript_annotations
                            annotations = gemini_generate_transcript_annotations(conversation_history=history, model_id=llm_model_tl, feedback_language=_tl_ann_lang)

                        for i, msg in enumerate(history):
                            if msg["role"] == "user":
                                idx_str = str(i)
                                if idx_str in annotations:
                                    msg["ai_comment"] = annotations[idx_str]

                        interview.conversation_history = json.dumps(history)
                        db.commit()
                        logger.info(f"✅ Transcript annotations saved for time-limited interview: {interview.interview_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to generate transcript annotations for time-limited interview: {e}")

                except Exception as e:
                    logger.error(f"❌ Error storing time-limited interview assessment: {e}")
                    db.rollback() if 'db' in locals() else None

                # Store the full assessment in the database (already done above)
                # But send neutral message to candidate (no feedback)
                logger.info(f"📊 Assessment generated and stored. Sending neutral message to candidate.")

                await websocket.send_json({
                    "type": "assessment",
                    "assessment": "**Interview Completed**\n\nThank you for your time! Our HR team will review your application and get back to you soon.\n\nWe appreciate your interest in this position.",
                    "time_limit_reached": True
                })
            except Exception as e:
                logger.error(f"❌ Error generating assessment for time-limited interview: {e}")
                await websocket.send_json({
                    "type": "assessment",
                    "assessment": "**Interview Completed**\n\nThank you for your time! Our HR team will review your application and get back to you soon.\n\nWe appreciate your interest in this position.",
                    "time_limit_reached": True
                })
        else:
            await websocket.send_json({
                "type": "assessment",
                "assessment": "**Interview Completed**\n\nThank you for your time! Our HR team will review your application and get back to you soon.\n\nWe appreciate your interest in this position.",
                "time_limit_reached": True
            })

        # Clean up
        if conversation_id in active_conversations:
            del active_conversations[conversation_id]
        if conversation_id in session_configs:
            del session_configs[conversation_id]
        if conversation_id in interview_start_times:
            del interview_start_times[conversation_id]
        cleanup_dedup_cache(conversation_id)

        # Wait for any final audio to finish playing before closing
        logger.info("⏳ Waiting 10 seconds for any audio to finish...")
        await asyncio.sleep(10)

        # Close WebSocket connection
        logger.info(f"🔌 Closing WebSocket connection after time limit")
        await websocket.close(code=1000, reason="Interview time limit reached")

        return False  # Interview ended

    return True  # Continue interview


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

@router.post("/{interview_id}/async/start")
async def start_async_interview(
    interview_id: str,
    request: AsyncInterviewStartRequest,
    db: Session = Depends(get_db)
):
    """Start an asynchronous interview - returns the first question."""
    if db is None:
        db = next(get_db())

    # Verify interview exists and email matches
    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    application = db.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == application.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if candidate.email != request.email:
        raise HTTPException(status_code=403, detail="Access denied. Email does not match interview candidate.")

    # Check interview mode
    job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == interview.job_offer_id).first()
    if not job_offer:
        raise HTTPException(status_code=404, detail="Job offer not found")

    if job_offer.interview_mode != "asynchronous":
        raise HTTPException(status_code=400, detail="This interview is not in asynchronous mode")

    # Allow resuming in_progress interviews or starting new ones even if previous ones are completed
    # Multiple interview attempts are allowed per application

    # If interview is in_progress, resume it (get current question from conversation)
    if interview.status == "in_progress" and interview.conversation_history:
        try:
            conversation_history = json.loads(interview.conversation_history)
            # Find the last assistant message (question)
            last_question = None
            for msg in reversed(conversation_history):
                if msg.get("role") == "assistant":
                    last_question = msg.get("content")
                    break

            if last_question:
                # Return the current question
                return {
                    "interview_id": interview_id,
                    "question_number": sum(1 for m in conversation_history if m.get("role") == "assistant"),
                    "question_text": last_question,
                    "question_audio": "",  # No audio for resumed interviews
                    "audio_format": "mp3",
                    "status": "in_progress",
                    "resumed": True
                }
        except:
            pass  # If parsing fails, start fresh

    # Get providers
    tts_provider = request.tts_provider or DEFAULT_TTS_PROVIDER
    stt_provider = request.stt_provider or DEFAULT_STT_PROVIDER
    llm_provider = request.llm_provider or DEFAULT_LLM_PROVIDER

    # Always use Gemini for LLM
    llm_provider = "gemini"

    tts_model = request.tts_model or TTS_PROVIDERS[tts_provider]["default_model"]
    stt_model = request.stt_model or STT_PROVIDERS[stt_provider]["default_model"]
    llm_model = request.llm_model or LLM_PROVIDERS[llm_provider]["default_model"]

    # Build interview context
    required_languages_list = []
    if job_offer.required_languages:
        try:
            required_languages_list = json.loads(job_offer.required_languages)
        except:
            pass

    interview_context = {
        "job_title": job_offer.title,
        "job_offer_description": job_offer.description,
        "candidate_cv_text": application.cv_text,
        "required_languages": job_offer.required_languages,
        "interview_start_language": job_offer.interview_start_language or "English",
        "required_languages_list": required_languages_list,
        "custom_questions": job_offer.custom_questions,
        "evaluation_weights": job_offer.evaluation_weights
    }

    # Generate opening greeting/question (with retry on quota)
    llm_funcs = get_llm_functions(llm_provider)
    greeting = _retry_on_quota(
        llm_funcs["generate_opening_greeting"],
        model_id=llm_model,
        interview_context=interview_context,
        candidate_name=candidate.full_name
    )

    # Generate audio for greeting (with TTS fallback)
    audio_base64 = ""
    tts_fallback = False
    try:
        tts_func = get_tts_function(tts_provider)
        audio_data = tts_func(greeting, model_id=tts_model, voice_id=None)
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
    except Exception as tts_err:
        logger.warning(f"⚠️ TTS failed for async greeting (will use browser fallback): {tts_err}")
        tts_fallback = True

    # Initialize conversation history
    conversation_history = [
        {"role": "assistant", "content": greeting}
    ]

    # Store provider preferences for later use
    provider_preferences = {
        "tts_provider": tts_provider,
        "tts_model": tts_model,
        "stt_provider": stt_provider,
        "stt_model": stt_model,
        "llm_provider": llm_provider,
        "llm_model": llm_model
    }

    # Initialize audio segments with first question
    audio_segments = [{
        "type": "question",
        "question_number": 1,
        "audio": audio_base64,
        "format": "mp3",
        "text": greeting,
        "timestamp": datetime.now().isoformat()
    }]

    # Update interview status, conversation, and provider preferences
    interview.status = "in_progress"
    interview.conversation_history = json.dumps(conversation_history)
    interview.provider_preferences = json.dumps(provider_preferences)
    if hasattr(interview, 'audio_segments'):
        interview.audio_segments = json.dumps(audio_segments)
    db.commit()

    logger.info(f"🎤 Started asynchronous interview: {interview_id} with providers: {llm_provider}/{llm_model}")

    return {
        "interview_id": interview_id,
        "question_number": 1,
        "question_text": greeting,
        "question_audio": audio_base64,
        "audio_format": "mp3",
        "tts_fallback": tts_fallback,
        "status": "in_progress"
    }


@router.post("/{interview_id}/async/submit-answer")
async def submit_async_answer(
    interview_id: str,
    request: AsyncInterviewAnswerRequest,
    db: Session = Depends(get_db)
):
    """Submit an answer in asynchronous interview - returns next question or assessment."""
    if db is None:
        db = next(get_db())

    # Verify interview exists and email matches
    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    application = db.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == application.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if candidate.email != request.email:
        raise HTTPException(status_code=403, detail="Access denied. Email does not match interview candidate.")

    if interview.status not in ["in_progress", "pending"]:
        raise HTTPException(status_code=400, detail="Interview is not in progress")

    # Get job offer and check mode
    job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == interview.job_offer_id).first()
    if not job_offer:
        raise HTTPException(status_code=404, detail="Job offer not found")

    if job_offer.interview_mode != "asynchronous":
        raise HTTPException(status_code=400, detail="This interview is not in asynchronous mode")

    # Decode audio
    try:
        audio_bytes = base64.b64decode(request.audio)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid audio data: {str(e)}")

    # Get conversation history
    conversation_history = []
    if interview.conversation_history:
        try:
            conversation_history = json.loads(interview.conversation_history)
        except:
            conversation_history = []

    # Get providers from stored preferences or use defaults
    provider_preferences = {}
    try:
        # Handle case where column might not exist yet (for old interviews)
        if hasattr(interview, 'provider_preferences') and interview.provider_preferences:
            try:
                provider_preferences = json.loads(interview.provider_preferences)
            except:
                provider_preferences = {}
    except AttributeError:
        # Column doesn't exist in database yet
        provider_preferences = {}

    tts_provider = provider_preferences.get("tts_provider") or DEFAULT_TTS_PROVIDER
    tts_model = provider_preferences.get("tts_model") or TTS_PROVIDERS[tts_provider]["default_model"]
    stt_provider = provider_preferences.get("stt_provider") or DEFAULT_STT_PROVIDER
    stt_model = provider_preferences.get("stt_model") or STT_PROVIDERS[stt_provider]["default_model"]

    llm_provider = "gemini"
    llm_model = provider_preferences.get("llm_model") or LLM_PROVIDERS[llm_provider]["default_model"]

    logger.info(f"📝 Using providers for async interview: LLM={llm_provider}/{llm_model}, TTS={tts_provider}/{tts_model}, STT={stt_provider}/{stt_model}")

    # Speech to Text — determine current language from conversation for accurate STT
    # Start with interview_start_language, but update based on detected language switches
    stt_lang = job_offer.interview_start_language or "English"
    lang_keywords = {
        "French": ["français", "francais", "french", "en français", "continuons en français"],
        "English": ["english", "anglais", "in english", "let's continue in english", "continue in english"],
        "Arabic": ["arabic", "arabe", "en arabe", "بالعربية"],
        "Spanish": ["spanish", "espagnol", "español", "en español"],
        "German": ["german", "allemand", "deutsch", "auf deutsch"]
    }
    for msg in conversation_history:
        if msg["role"] == "assistant":
            content_lower = msg["content"].lower()
            for lang, keywords in lang_keywords.items():
                if any(keyword in content_lower for keyword in keywords) and stt_lang != lang:
                    stt_lang = lang
    stt_lang_code = get_language_code(stt_lang)
    stt_func = get_stt_function(stt_provider)
    user_text = stt_func(audio_bytes, model_id=stt_model, language_code=stt_lang_code or None)

    if not user_text.strip():
        raise HTTPException(status_code=400, detail="Could not transcribe audio. Please try again.")

    # Add user response to conversation
    conversation_history.append({"role": "user", "content": user_text})

    # Build interview context
    required_languages_list = []
    if job_offer.required_languages:
        try:
            required_languages_list = json.loads(job_offer.required_languages)
        except:
            pass

    interview_context = {
        "job_title": job_offer.title,
        "job_offer_description": job_offer.description,
        "candidate_cv_text": application.cv_text,
        "required_languages": job_offer.required_languages,
        "interview_start_language": job_offer.interview_start_language or "English",
        "required_languages_list": required_languages_list,
        "custom_questions": job_offer.custom_questions,
        "evaluation_weights": job_offer.evaluation_weights
    }

    try:
        # Check if we should generate assessment (after a reasonable number of questions)
        question_count = sum(1 for msg in conversation_history if msg["role"] == "assistant")

        llm_funcs = get_llm_functions(llm_provider)

        # Track tested languages based on AI language switches tracking
        tested_languages = set()
        start_language = interview_context.get("interview_start_language", "English")
        tested_languages.add(start_language)
        current_language = start_language
        consecutive_language_questions = 0

        lang_keywords = {
            "French": ["français", "francais", "french", "en français", "continuons en français"],
            "English": ["english", "anglais", "in english", "let's continue in english"],
            "Arabic": ["arabic", "arabe", "en arabe", "بالعربية"],
            "Spanish": ["spanish", "espagnol", "español", "en español"],
            "German": ["german", "allemand", "deutsch", "auf deutsch"]
        }

        for msg in conversation_history:
            if msg["role"] == "assistant":
                content_lower = msg["content"].lower()
                switched = False
                for lang, keywords in lang_keywords.items():
                    if any(keyword in content_lower for keyword in keywords) and current_language != lang:
                        tested_languages.add(lang)
                        current_language = lang
                        consecutive_language_questions = 1
                        switched = True
                        break
                if not switched:
                    consecutive_language_questions += 1

        all_languages_tested = True
        if required_languages_list:
            for req_lang in required_languages_list:
                if req_lang not in tested_languages:
                    all_languages_tested = False
                    break

        interview_context["tested_languages"] = list(tested_languages)
        interview_context["current_language"] = current_language
        interview_context["questions_in_current_language"] = consecutive_language_questions

        # Determine if we should end the interview
        # Enforce minimum 5 questions, prioritize completing required languages
        if all_languages_tested:
            should_end = question_count >= 5
        else:
            should_end = question_count >= 10  # absolute maximum questions

        if should_end:
            # Save final answer audio segment
            audio_segments = []
            if hasattr(interview, 'audio_segments') and interview.audio_segments:
                try:
                    audio_segments = json.loads(interview.audio_segments)
                except:
                    audio_segments = []

            # Save candidate's final answer audio
            audio_segments.append({
                "type": "answer",
                "question_number": request.question_number,
                "audio": request.audio,  # User's answer audio (webm)
                "format": "webm",
                "text": user_text,
                "timestamp": datetime.now().isoformat()
            })

            # Mark as completed immediately so candidate gets instant feedback
            interview.status = "completed"
            interview.completed_at = datetime.now()
            interview.conversation_history = json.dumps(conversation_history)
            if hasattr(interview, 'audio_segments'):
                interview.audio_segments = json.dumps(audio_segments)
            application.interview_completed_at = datetime.now()
            db.commit()

            logger.info(f"✅ Completed asynchronous interview: {interview_id} — generating assessment in background")

            # Generate assessment + annotations in background thread (like the /end endpoint)
            _bg_interview_id = interview.interview_id
            _bg_application_id = application.application_id
            _bg_conv_history = list(conversation_history)
            _bg_llm_model = llm_model
            _bg_interview_context = dict(interview_context)
            _bg_start_lang = interview_context.get("interview_start_language")

            def _run_submit_assessment_bg():
                try:
                    db_bg = SessionLocal()
                    try:
                        logger.info(f"📝 [BG] Generating assessment for completed interview: {_bg_interview_id}")
                        _bg_llm_funcs = get_llm_functions("gemini")
                        assessment = _bg_llm_funcs["generate_assessment"](
                            conversation_history=_bg_conv_history,
                            model_id=_bg_llm_model,
                            interview_context=_bg_interview_context,
                        )
                        recommendation = extract_recommendation(assessment)

                        iv = db_bg.query(DBInterview).filter(DBInterview.interview_id == _bg_interview_id).first()
                        if iv:
                            iv.assessment = assessment
                            iv.recommendation = recommendation
                            iv.evaluation_scores = json.dumps(extract_detailed_scores(assessment))
                        app = db_bg.query(DBApplication).filter(DBApplication.application_id == _bg_application_id).first()
                        if app:
                            app.interview_assessment = assessment
                            app.interview_recommendation = recommendation
                            app.updated_at = datetime.utcnow()
                        db_bg.commit()
                        logger.info(f"✅ [BG] Assessment saved for interview: {_bg_interview_id}")

                        # Generate transcript annotations
                        try:
                            from backend.services.language_llm_openai import generate_transcript_annotations as gemini_ann
                            annotations = gemini_ann(
                                conversation_history=_bg_conv_history,
                                model_id=_bg_llm_model,
                                feedback_language=_bg_start_lang
                            )
                            for i, msg in enumerate(_bg_conv_history):
                                if msg["role"] == "user":
                                    idx_str = str(i)
                                    if idx_str in annotations:
                                        msg["ai_comment"] = annotations[idx_str]
                            if iv:
                                iv.conversation_history = json.dumps(_bg_conv_history)
                                db_bg.commit()
                            logger.info(f"✅ [BG] Transcript annotations saved for interview: {_bg_interview_id}")
                        except Exception as e:
                            logger.error(f"❌ [BG] Transcript annotations failed: {e}")
                    except Exception as e:
                        logger.error(f"❌ [BG] Assessment generation failed for {_bg_interview_id}: {e}")
                        db_bg.rollback()
                        try:
                            iv_err = db_bg.query(DBInterview).filter(DBInterview.interview_id == _bg_interview_id).first()
                            if iv_err and not iv_err.assessment:
                                error_msg = str(e)
                                if "quota" in error_msg.lower() or "429" in error_msg or "resource" in error_msg.lower():
                                    iv_err.assessment = "[ASSESSMENT_FAILED:QUOTA] API quota exceeded. Please reload credits and regenerate the assessment."
                                else:
                                    iv_err.assessment = f"[ASSESSMENT_FAILED] Assessment generation failed: {error_msg[:200]}. You can regenerate it from the admin panel."
                                db_bg.commit()
                        except Exception:
                            pass
                    finally:
                        db_bg.close()
                except Exception as e:
                    logger.error(f"❌ [BG] Background assessment thread error: {e}")

            threading.Thread(target=_run_submit_assessment_bg, daemon=True).start()

            return {
                "interview_id": interview_id,
                "status": "completed",
                "user_text": user_text,
            }
        else:
            # Generate next question (with retry on quota)
            next_question = _retry_on_quota(
                llm_funcs["generate_response"],
                conversation_history=conversation_history[:-1],  # Exclude the just-added user message
                user_message=user_text,
                model_id=llm_model,
                interview_context=interview_context
            )

            # Detect implicit explicit conclusion and strip token before TTS
            if "[interview_concluded]" in next_question.lower():
                next_question = re.sub(r'\[INTERVIEW_CONCLUDED\]', '', next_question, flags=re.IGNORECASE).strip()

            # Generate audio for question (with TTS fallback)
            audio_base64 = ""
            tts_fallback = False
            try:
                tts_func = get_tts_function(tts_provider)
                audio_data = tts_func(next_question, model_id=tts_model, voice_id=None)
                audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            except Exception as tts_err:
                logger.warning(f"⚠️ TTS failed for async question (will use browser fallback): {tts_err}")
                tts_fallback = True

            # Add assistant response to conversation
            conversation_history.append({"role": "assistant", "content": next_question})

            # Save audio segments (question and answer separately)
            audio_segments = []
            if hasattr(interview, 'audio_segments') and interview.audio_segments:
                try:
                    audio_segments = json.loads(interview.audio_segments)
                except:
                    audio_segments = []

            # Save candidate's answer audio
            audio_segments.append({
                "type": "answer",
                "question_number": request.question_number,
                "audio": request.audio,  # User's answer audio (webm)
                "format": "webm",
                "text": user_text,
                "timestamp": datetime.now().isoformat()
            })

            # Save AI's question audio
            audio_segments.append({
                "type": "question",
                "question_number": question_count + 1,
                "audio": audio_base64,  # AI's question audio (mp3)
                "format": "mp3",
                "text": next_question,
                "timestamp": datetime.now().isoformat()
            })

            # Update interview
            interview.conversation_history = json.dumps(conversation_history)
            if hasattr(interview, 'audio_segments'):
                interview.audio_segments = json.dumps(audio_segments)
            db.commit()

            logger.info(f"📝 Question {question_count + 1} generated for interview: {interview_id}")

            return {
                "interview_id": interview_id,
                "question_number": question_count + 1,
                "question_text": next_question,
                "question_audio": audio_base64,
                "audio_format": "mp3",
                "tts_fallback": tts_fallback,
                "status": "in_progress",
                "user_text": user_text,
            }
    except Exception as e:
        logger.error(f"❌ Error in submit_async_answer: {str(e)}", exc_info=True)
        # Check if conversation history already updated in memory
        if len(conversation_history) > 0 and conversation_history[-1]["role"] == "user":
             # Remove the user message if we couldn't generate response to avoid state mismatch
             conversation_history.pop()
        raise HTTPException(status_code=500, detail=f"Error processing answer: {str(e)}")


@router.post("/{interview_id}/async/save-recording")
async def save_async_interview_recording(
    interview_id: str,
    request: AsyncInterviewRecordingRequest,
    db: Session = Depends(get_db)
):
    """Save the full interview recording (user audio + AI audio combined)."""
    if db is None:
        db = next(get_db())

    # Verify interview exists and email matches
    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    application = db.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == application.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if candidate.email != request.email:
        raise HTTPException(status_code=403, detail="Access denied. Email does not match interview candidate.")

    # Validate that we have at least some audio to save
    if not request.user_audio and (not request.ai_audio_chunks or len(request.ai_audio_chunks) == 0):
        logger.warning(f"⚠️ No audio data provided for interview {interview_id}")
        return {
            "interview_id": interview_id,
            "status": "skipped",
            "message": "No audio data to save"
        }

    # Try to combine audio with pydub, but fallback to saving user audio if it fails
    try:
        from pydub import AudioSegment
        from io import BytesIO

        combined_audio = None
        user_audio_valid = False

        # Try to process user audio
        if request.user_audio:
            try:
                user_audio_bytes = base64.b64decode(request.user_audio)
                if len(user_audio_bytes) > 0:
                    user_audio = AudioSegment.from_file(BytesIO(user_audio_bytes), format="webm")
                    combined_audio = user_audio
                    user_audio_valid = True
                    logger.info(f"✅ Processed user audio: {len(user_audio_bytes)} bytes")
            except Exception as e:
                logger.warning(f"⚠️ Could not process user audio with pydub: {e}")
                # Continue to try AI audio or save user audio as-is

        # Process AI audio chunks
        if request.ai_audio_chunks and len(request.ai_audio_chunks) > 0:
            # Sort AI audio chunks by timestamp
            ai_chunks = sorted(request.ai_audio_chunks, key=lambda x: x.get("timestamp", 0))

            # If we don't have user audio, start with first AI chunk
            if not user_audio_valid and len(ai_chunks) > 0:
                try:
                    first_chunk = ai_chunks[0]
                    ai_audio_bytes = base64.b64decode(first_chunk["audio"])
                    ai_format = first_chunk.get("format", "mp3")
                    combined_audio = AudioSegment.from_file(BytesIO(ai_audio_bytes), format=ai_format)
                    ai_chunks = ai_chunks[1:]  # Skip first chunk as we already added it
                    logger.info(f"✅ Started with AI audio chunk")
                except Exception as e:
                    logger.warning(f"⚠️ Could not process first AI audio chunk: {e}")

            # Append remaining AI audio chunks
            for chunk in ai_chunks:
                try:
                    ai_audio_bytes = base64.b64decode(chunk["audio"])
                    ai_format = chunk.get("format", "mp3")
                    ai_audio = AudioSegment.from_file(BytesIO(ai_audio_bytes), format=ai_format)
                    # Add a small silence between chunks
                    if combined_audio:
                        combined_audio += AudioSegment.silent(duration=500)  # 500ms silence
                        combined_audio += ai_audio
                    else:
                        combined_audio = ai_audio
                except Exception as e:
                    logger.warning(f"⚠️ Error processing AI audio chunk: {e}")
                    continue

        # Export combined audio to MP3
        if combined_audio:
            try:
                output = BytesIO()
                combined_audio.export(output, format="mp3", bitrate="128k")
                output.seek(0)

                audio_bytes = output.read()
                audio_key = f"recordings/{interview_id}.mp3"
                s3_upload(audio_bytes, audio_key, content_type="audio/mpeg", local_dir=UPLOADS_DIR)

                # Store key in database (or base64 as fallback for backward compat)
                if is_s3_enabled():
                    interview.recording_audio = f"s3://{audio_key}"
                else:
                    interview.recording_audio = base64.b64encode(audio_bytes).decode('utf-8')
                db.commit()

                logger.info(f"✅ Saved combined interview recording for interview: {interview_id}")

                return {
                    "interview_id": interview_id,
                    "status": "saved",
                    "message": "Recording saved successfully"
                }
            except Exception as e:
                logger.error(f"❌ Error exporting combined audio: {e}", exc_info=True)
                # Fall through to save user audio only
    except ImportError as e:
        logger.warning(f"⚠️ pydub not available: {e}")
    except Exception as e:
        logger.error(f"❌ Error in audio processing: {e}", exc_info=True)
        # Continue to fallback

    # Fallback: Save user audio only if combining failed or pydub not available
    if request.user_audio:
        try:
            # Validate base64 before saving
            try:
                test_decode = base64.b64decode(request.user_audio)
                if len(test_decode) == 0:
                    raise ValueError("User audio is empty after decoding")
            except Exception as e:
                logger.error(f"❌ Invalid user audio data: {e}")
                raise HTTPException(status_code=400, detail=f"Invalid audio data: {str(e)}")

            interview.recording_audio = request.user_audio  # Store user audio as-is (base64 webm)
            db.commit()
            logger.info(f"✅ Saved user audio only for interview: {interview_id} ({len(request.user_audio)} chars)")
            return {
                "interview_id": interview_id,
                "status": "saved",
                "message": "Recording saved (user audio only - audio combining not available)"
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error saving user audio to database: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to save recording: {str(e)}")


@router.post("/{interview_id}/async/upload-video")
async def upload_interview_video(
    interview_id: str,
    email: str = Form(...),
    video_file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload video recording for an interview."""
    if db is None:
        db = next(get_db())

    # Verify interview exists
    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    # Verify application and candidate
    application = db.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == application.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if candidate.email != email:
        raise HTTPException(status_code=403, detail="Access denied. Email does not match interview candidate.")

    try:
        # Save video file
        file_extension = "webm"  # Default for MediaRecorder
        if video_file.filename and '.' in video_file.filename:
            file_extension = video_file.filename.split('.')[-1]

        video_key = f"videos/{interview_id}.{file_extension}"
        content = await video_file.read()
        s3_upload(content, video_key, content_type=f"video/{file_extension}", local_dir=UPLOADS_DIR)

        interview.recording_video = video_key
        db.commit()

        logger.info(f"✅ Video uploaded successfully for interview {interview_id}: {video_key}")

        return {
            "interview_id": interview_id,
            "status": "uploaded",
            "file_path": interview.recording_video,
            "message": "Video uploaded successfully"
        }
    except Exception as e:
        logger.error(f"❌ Error uploading video: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload video: {str(e)}")


@router.post("/{interview_id}/snapshots")
async def upload_interview_snapshots(
    interview_id: str,
    request: SnapshotUploadRequest,
    db: Session = Depends(get_db)
):
    """Upload periodic identity verification snapshots for an interview."""
    if db is None:
        db = next(get_db())

    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    application = db.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == application.candidate_id).first()
    if not candidate or candidate.email != request.email:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        # Create a composite image grid from snapshots
        snapshot_keys = []
        for i, snap in enumerate(request.snapshots):
            img_bytes = base64.b64decode(snap["image"])
            snap_key = f"snapshots/{interview_id}/{i:03d}.jpg"
            s3_upload(img_bytes, snap_key, content_type="image/jpeg", local_dir=UPLOADS_DIR)
            snapshot_keys.append({
                "key": snap_key,
                "timestamp": snap.get("timestamp", "")
            })

        # Store snapshot metadata as the video field (repurposed)
        interview.recording_video = json.dumps({
            "type": "snapshots",
            "count": len(snapshot_keys),
            "snapshots": snapshot_keys
        })
        db.commit()

        logger.info(f"✅ {len(snapshot_keys)} snapshots uploaded for interview {interview_id}")
        return {"interview_id": interview_id, "status": "uploaded", "count": len(snapshot_keys)}
    except Exception as e:
        logger.error(f"❌ Error uploading snapshots: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload snapshots: {str(e)}")


@router.post("/{interview_id}/async/end")
async def end_async_interview(
    interview_id: str,
    request: AsyncInterviewEndRequest,
    db: Session = Depends(get_db)
):
    """End an asynchronous interview - marks as completed and generates assessment in background."""
    if db is None:
        db = next(get_db())

    # Verify interview exists and email matches
    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    application = db.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    candidate = db.query(DBCandidate).filter(DBCandidate.candidate_id == application.candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if candidate.email != request.email:
        raise HTTPException(status_code=403, detail="Access denied. Email does not match interview candidate.")

    # Get job offer for interview context
    job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == interview.job_offer_id).first()
    if not job_offer:
        raise HTTPException(status_code=404, detail="Job offer not found")

    # Get conversation history
    conversation_history = []
    if interview.conversation_history:
        try:
            conversation_history = json.loads(interview.conversation_history)
        except:
            conversation_history = []

    # Mark as completed immediately so candidate can leave
    interview.status = "completed"
    interview.completed_at = datetime.utcnow()
    if conversation_history:
        interview.conversation_history = json.dumps(conversation_history)
    application.interview_completed_at = datetime.utcnow()
    db.commit()

    # Generate assessment in background thread
    if conversation_history and len(conversation_history) > 0:
        # Collect data needed for background thread (can't use DB session across threads)
        _interview_id = interview.interview_id
        _application_id = application.application_id
        _provider_prefs_str = getattr(interview, 'provider_preferences', None) or ""
        _job_title = job_offer.title
        _job_desc = job_offer.description
        _cv_text = application.cv_text
        _required_langs = job_offer.required_languages
        _start_lang = job_offer.interview_start_language or "English"
        _custom_questions = job_offer.custom_questions
        _eval_weights = job_offer.evaluation_weights
        _conv_history = list(conversation_history)  # copy

        def _run_assessment_background():
            try:
                db_bg = SessionLocal()
                try:
                    provider_preferences = {}
                    if _provider_prefs_str:
                        try:
                            provider_preferences = json.loads(_provider_prefs_str)
                        except:
                            pass

                    llm_provider = "gpt"
                    llm_model = provider_preferences.get("llm_model") or LLM_PROVIDERS[llm_provider]["default_model"]

                    logger.info(f"📝 [BG] Generating assessment for interview: {_interview_id}")

                    required_languages_list = []
                    if _required_langs:
                        try:
                            required_languages_list = json.loads(_required_langs)
                        except:
                            pass

                    interview_context = {
                        "job_title": _job_title,
                        "job_offer_description": _job_desc,
                        "candidate_cv_text": _cv_text,
                        "required_languages": _required_langs,
                        "interview_start_language": _start_lang,
                        "required_languages_list": required_languages_list,
                        "custom_questions": _custom_questions,
                        "evaluation_weights": _eval_weights,
                    }

                    llm_funcs = get_llm_functions(llm_provider)
                    assessment = llm_funcs["generate_assessment"](
                        conversation_history=_conv_history,
                        model_id=llm_model,
                        interview_context=interview_context,
                    )

                    recommendation = extract_recommendation(assessment)

                    # Update DB
                    iv = db_bg.query(DBInterview).filter(DBInterview.interview_id == _interview_id).first()
                    if iv:
                        iv.assessment = assessment
                        iv.recommendation = recommendation
                        iv.evaluation_scores = json.dumps(extract_detailed_scores(assessment))
                    app = db_bg.query(DBApplication).filter(DBApplication.application_id == _application_id).first()
                    if app:
                        app.interview_assessment = assessment
                        app.interview_recommendation = recommendation
                        app.updated_at = datetime.utcnow()
                    db_bg.commit()
                    logger.info(f"✅ [BG] Assessment saved for interview: {_interview_id}")

                    # Generate transcript annotations
                    try:
                        if llm_provider == "gpt":
                            from backend.services.language_llm_openai import generate_transcript_annotations as gemini_ann
                            annotations = gemini_ann(conversation_history=_conv_history, model_id=llm_model, feedback_language=_start_lang)
                        else:
                            from backend.services.language_llm_openai import generate_transcript_annotations as gem_ann
                            annotations = gem_ann(conversation_history=_conv_history, model_id=llm_model, feedback_language=_start_lang)

                        for i, msg in enumerate(_conv_history):
                            if msg["role"] == "user":
                                idx_str = str(i)
                                if idx_str in annotations:
                                    msg["ai_comment"] = annotations[idx_str]

                        if iv:
                            iv.conversation_history = json.dumps(_conv_history)
                            db_bg.commit()
                        logger.info(f"✅ [BG] Transcript annotations saved for interview: {_interview_id}")
                    except Exception as e:
                        logger.error(f"❌ [BG] Transcript annotations failed: {e}")

                except Exception as e:
                    logger.error(f"❌ [BG] Assessment generation failed for {_interview_id}: {e}")
                    db_bg.rollback()
                finally:
                    db_bg.close()
            except Exception as e:
                logger.error(f"❌ [BG] Background assessment thread error: {e}")

        threading.Thread(target=_run_assessment_background, daemon=True).start()

    logger.info(f"✅ Marked async interview as completed (assessment generating in background): {interview_id}")

    return {
        "interview_id": interview_id,
        "status": "completed",
        "message": "Interview ended successfully. Assessment is being generated."
    }
