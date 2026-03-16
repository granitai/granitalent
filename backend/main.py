"""FastAPI application for AI Interviewer."""
import asyncio
import base64
import json
import sys
import os
import logging
import time
import re

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import uvicorn

from backend.config import (
    TTS_PROVIDERS, STT_PROVIDERS, LLM_PROVIDERS,
    DEFAULT_TTS_PROVIDER, DEFAULT_STT_PROVIDER, DEFAULT_LLM_PROVIDER,
    INTERVIEW_TIME_LIMIT_MINUTES
)
from backend.models.conversation import ConversationManager
from backend.services.storage import upload_file as s3_upload
from backend.database import init_db, get_db
from backend.models.db_models import (
    JobOffer as DBJobOffer,
    Application as DBApplication,
    CVEvaluation as DBCVEvaluation,
    Interview as DBInterview,
)
from backend.services.elevenlabs_stt_streaming import ElevenLabsSTTStreaming

# Import shared state and utilities
from backend.state import (
    CONCLUSION_PHRASES, UPLOADS_DIR,
    active_conversations, session_configs, streaming_stt_sessions,
    interview_start_times, cv_evaluations,
)
from backend.utils import (
    get_language_code, is_duplicate_message, cleanup_dedup_cache,
    extract_detailed_scores, extract_recommendation,
    get_tts_function, get_stt_function, is_streaming_stt_provider,
    get_voice_id, get_llm_functions,
)

# Import routers
from backend.routers import (
    auth, providers, cv, public,
    admin_jobs, admin_applications, admin_interviews,
    admin_candidates, admin_dashboard, candidate_interviews,
)

app = FastAPI(title="AI Interviewer API")

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database tables on application startup."""
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.warning(f"Database initialization warning: {e} (continuing with in-memory storage)")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount uploads directory for static file serving
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# Include all routers
app.include_router(auth.router)
app.include_router(providers.router)
app.include_router(cv.router)
app.include_router(public.router)
app.include_router(admin_jobs.router)
app.include_router(admin_applications.router)
app.include_router(admin_interviews.router)
app.include_router(admin_candidates.router)
app.include_router(admin_dashboard.router)
app.include_router(candidate_interviews.router)


async def handle_precheck_response(
    conversation,
    user_text: str,
    config: dict,
    llm_funcs: dict,
    websocket: WebSocket,
    conversation_id: str
) -> bool:
    """
    Handle responses during pre-check phase.
    
    Returns:
        True if we should continue processing (phase transitioned), False if handled here
    """
    phase = conversation.get_current_phase()
    
    if phase == ConversationManager.PHASE_AUDIO_CHECK:
        # Any response means audio is working - move to name check
        logger.info("✅ Audio check passed, moving to name check")
        conversation.set_phase(ConversationManager.PHASE_NAME_CHECK)
        
        # Generate name request message
        interview_start_language = conversation.interview_start_language if conversation.interview_start_language else None
        name_request_text = llm_funcs["generate_name_request"](model_id=config["llm_model"], language=interview_start_language)
        conversation.add_message("interviewer", name_request_text)
        
        # Convert to speech
        tts_func = get_tts_function(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
        voice_id = get_voice_id(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
        tts_model = config.get("tts_model")
        
        try:
            audio_bytes = tts_func(name_request_text, voice_id, tts_model)
            audio_format = "mp3"
        except ValueError as e:
            error_msg = str(e)
            logger.error(f"TTS Error: {error_msg}")
            await websocket.send_json({"type": "error", "message": error_msg})
            return False
        except Exception as e:
            logger.error(f"TTS Error: {e}")
            await websocket.send_json({
                "type": "error",
                "message": "Text-to-speech service error. Please try again or switch to a different TTS provider."
            })
            return False

        audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

        await websocket.send_json({
            "type": "response",
            "user_text": user_text,
            "interviewer_text": name_request_text,
            "audio": audio_base64,
            "audio_format": audio_format,
            "phase": conversation.get_current_phase()
        })
        return False  # Handled, don't continue normal processing

    elif phase == ConversationManager.PHASE_NAME_CHECK:
        # Extract name from user response
        # Try to find name patterns in the response
        # Look for "my name is X" or "I'm X" or "I am X" or just a name
        name_patterns = [
            r"(?:my name is|i'm|i am|call me|it's|it is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
            r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",  # First capitalized words
        ]
        
        candidate_name = None
        name_spelling = None
        
        for pattern in name_patterns:
            match = re.search(pattern, user_text, re.IGNORECASE)
            if match:
                candidate_name = match.group(1).strip()
                break
        
        # Look for spelling (usually after "spelled" or "spell it")
        spelling_match = re.search(r"(?:spelled|spell it|spelling is|it's spelled)\s+([A-Z\s-]+)", user_text, re.IGNORECASE)
        if spelling_match:
            name_spelling = spelling_match.group(1).strip()
        
        # If no name found, use first few words as fallback
        if not candidate_name:
            words = user_text.split()
            if words:
                # Take first 2-3 capitalized words as name
                name_words = [w for w in words[:3] if w and w[0].isupper()]
                if name_words:
                    candidate_name = " ".join(name_words)
        
        # Use CV name as the confirmed name (source of truth)
        # The spoken name is just for verification - we always use CV name
        cv_name = conversation.cv_candidate_name
        if cv_name:
            # CV name is the source of truth - use it as confirmed name
            conversation.confirmed_candidate_name = cv_name
            logger.info(f"✅ Using CV candidate name (source of truth): {cv_name}")
            logger.info(f"📝 Spoken name for verification: {candidate_name} (spelling: {name_spelling})")
        elif candidate_name:
            # Fallback: use spoken name if no CV name available
            conversation.set_candidate_name(candidate_name, name_spelling)
            logger.info(f"✅ Got candidate name: {candidate_name} (spelling: {name_spelling})")
        
        # Store confirmed candidate name in session config for database storage
        confirmed_name = conversation.get_confirmed_name()
        if conversation_id and conversation_id in session_configs and confirmed_name:
            session_configs[conversation_id]["candidate_name"] = confirmed_name
        
        # Move to actual interview phase
        conversation.set_phase(ConversationManager.PHASE_INTERVIEW)
        
        # Generate actual interview greeting (starting with full time limit)
        interview_context = conversation.get_interview_context(time_remaining_minutes=INTERVIEW_TIME_LIMIT_MINUTES, total_interview_minutes=INTERVIEW_TIME_LIMIT_MINUTES)
        greeting_text = llm_funcs["generate_opening_greeting"](
            model_id=config["llm_model"],
            interview_context=interview_context,
            candidate_name=conversation.get_candidate_name()
        )
        conversation.add_message("interviewer", greeting_text)
        
        # Convert to speech
        tts_func = get_tts_function(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
        voice_id = get_voice_id(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
        tts_model = config.get("tts_model")
        
        try:
            audio_bytes = tts_func(greeting_text, voice_id, tts_model)
            audio_format = "mp3"
        except ValueError as e:
            error_msg = str(e)
            logger.error(f"TTS Error: {error_msg}")
            await websocket.send_json({"type": "error", "message": error_msg})
            return False
        except Exception as e:
            logger.error(f"TTS Error: {e}")
            await websocket.send_json({
                "type": "error",
                "message": "Text-to-speech service error. Please try again or switch to a different TTS provider."
            })
            return False
        
        audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        await websocket.send_json({
            "type": "response",
            "user_text": user_text,
            "interviewer_text": greeting_text,
            "audio": audio_base64,
            "audio_format": audio_format,
            "phase": conversation.get_current_phase(),
            "candidate_name": candidate_name
        })
        return False  # Handled, don't continue normal processing
    
    # Not in pre-check phase, continue normal processing
    return True


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "AI Interviewer API", "status": "running"}


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


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
                            from backend.services.language_llm_openai import generate_transcript_annotations
                            annotations = generate_transcript_annotations(conversation_history=history, model_id=llm_model_tl, feedback_language=_tl_ann_lang)
                        else:
                            from backend.services.language_llm_openai import generate_transcript_annotations
                            annotations = generate_transcript_annotations(conversation_history=history, model_id=llm_model_tl, feedback_language=_tl_ann_lang)
                        
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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time communication."""
    await websocket.accept()
    
    conversation_id = None
    conversation = None
    
    try:
        # Wait for conversation initialization
        init_message = await websocket.receive_text()
        init_data = json.loads(init_message)
        
        if init_data.get("type") == "start_interview":
            # Support both evaluation_id (legacy) and application_id/interview_id (new)
            evaluation_id = init_data.get("evaluation_id")
            application_id = init_data.get("application_id")
            interview_id = init_data.get("interview_id")
            
            logger.info(f"🚀 Starting interview - evaluation_id: {evaluation_id}, application_id: {application_id}, interview_id: {interview_id}")
            
            db_ws = next(get_db())
            candidate_cv_text = ""
            job_offer = None
            job_offer_id = None
            
            # Try to get from database first (new flow) - this should be the primary path
            if application_id or interview_id:
                logger.info(f"📋 Using database flow with application_id={application_id}, interview_id={interview_id}")
                interview = None
                application = None
                
                if interview_id:
                    interview = db_ws.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
                    if interview and interview.application_id:
                        application = db_ws.query(DBApplication).filter(DBApplication.application_id == interview.application_id).first()
                elif application_id:
                    application = db_ws.query(DBApplication).filter(DBApplication.application_id == application_id).first()
                    if application:
                        interview = db_ws.query(DBInterview).filter(DBInterview.application_id == application_id).order_by(DBInterview.created_at.desc()).first()
                
                if not application:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Application not found. Please ensure you have a valid interview invitation."
                    })
                    return
                
                # Check if interview is pending
                if interview and interview.status != "pending":
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Interview is already {interview.status}. Cannot start again."
                    })
                    return
                
                # Get CV text from application
                candidate_cv_text = application.cv_text or ""
                job_offer_id = application.job_offer_id
                
                # Extract candidate name from application (source of truth)
                candidate_name_from_cv = None
                if application.candidate:
                    candidate_name_from_cv = application.candidate.full_name
                    logger.info(f"📝 Candidate name from CV: {candidate_name_from_cv}")
                
                logger.info(f"✅ Found application - CV length: {len(candidate_cv_text)} chars, Job offer ID: {job_offer_id}")
                
                if not candidate_cv_text:
                    await websocket.send_json({
                        "type": "error",
                        "message": "CV text not found in application. Please contact support."
                    })
                    return
                
                # Get job offer
                db_job_offer = db_ws.query(DBJobOffer).filter(DBJobOffer.offer_id == job_offer_id).first()
                if not db_job_offer:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Job offer not found. Please contact support."
                    })
                    return
                
                from backend.models.job_offer import JobOffer
                job_offer = JobOffer(
                    title=db_job_offer.title,
                    description=db_job_offer.description,
                    required_skills=db_job_offer.required_skills or "",
                    experience_level=db_job_offer.experience_level or "",
                    education_requirements=db_job_offer.education_requirements or "",
                    offer_id=db_job_offer.offer_id
                )
                
                logger.info(f"✅ Job offer loaded: {job_offer.title}")
                
                # Store language requirements and duration for interview
                required_languages = db_job_offer.required_languages or ""
                interview_start_language = db_job_offer.interview_start_language or ""
                interview_duration_minutes = db_job_offer.interview_duration_minutes or INTERVIEW_TIME_LIMIT_MINUTES
                custom_questions = db_job_offer.custom_questions or ""
                evaluation_weights = db_job_offer.evaluation_weights or ""
            else:
                # Initialize language variables if not set
                required_languages = ""
                interview_start_language = ""
                custom_questions = ""
                evaluation_weights = ""
            
            # Legacy flow: use evaluation_id from memory
            if evaluation_id and not job_offer:
                if evaluation_id not in cv_evaluations:
                    await websocket.send_json({
                        "type": "error",
                        "message": "CV evaluation not found. Please upload and evaluate your CV first."
                    })
                    return
                
                evaluation = cv_evaluations[evaluation_id]
                if evaluation["status"] != "approved":
                    await websocket.send_json({
                        "type": "error",
                        "message": f"CV evaluation not approved. {evaluation.get('reasoning', 'Please check your CV and try again.')}"
                    })
                    return
                
                # Get job offer details for interview context
                job_offer_id = evaluation.get("job_offer_id")
                if job_offer_id:
                    db_job_offer = db_ws.query(DBJobOffer).filter(DBJobOffer.offer_id == job_offer_id).first()
                    if db_job_offer:
                        from backend.models.job_offer import JobOffer
                        job_offer = JobOffer(
                            title=db_job_offer.title,
                            description=db_job_offer.description,
                            required_skills=db_job_offer.required_skills or "",
                            experience_level=db_job_offer.experience_level or "",
                            education_requirements=db_job_offer.education_requirements or "",
                            offer_id=db_job_offer.offer_id
                        )
                        # Get language requirements and duration
                        required_languages = db_job_offer.required_languages or ""
                        interview_start_language = db_job_offer.interview_start_language or ""
                        interview_duration_minutes = db_job_offer.interview_duration_minutes or INTERVIEW_TIME_LIMIT_MINUTES
                        custom_questions = db_job_offer.custom_questions or ""
                        evaluation_weights = db_job_offer.evaluation_weights or ""
                
                candidate_cv_text = evaluation.get("parsed_cv_text", "")
            
            # Ensure we have language and duration variables initialized
            if 'required_languages' not in locals():
                required_languages = ""
            if 'interview_start_language' not in locals():
                interview_start_language = ""
            if 'interview_duration_minutes' not in locals():
                interview_duration_minutes = INTERVIEW_TIME_LIMIT_MINUTES
            if 'custom_questions' not in locals():
                custom_questions = ""
            if 'evaluation_weights' not in locals():
                evaluation_weights = ""
            
            # Create new conversation with job and candidate context
            conversation_id = f"conv_{len(active_conversations)}"
            conversation = ConversationManager(
                job_offer_description=job_offer.get_full_description() if job_offer else None,
                candidate_cv_text=candidate_cv_text,
                job_title=job_offer.title if job_offer else None,
                required_languages=required_languages,
                interview_start_language=interview_start_language,
                custom_questions=custom_questions,
                evaluation_weights=evaluation_weights
            )
            # Set CV candidate name if available (source of truth)
            if 'candidate_name_from_cv' in locals() and candidate_name_from_cv:
                conversation.set_cv_candidate_name(candidate_name_from_cv)
                logger.info(f"✅ Set CV candidate name: {candidate_name_from_cv}")
            active_conversations[conversation_id] = conversation
            
            logger.info(f"📋 Interview context set - Job: {job_offer.title if job_offer else 'Unknown'}, CV: {len(candidate_cv_text)} chars")
            
            # Store session configuration — always OpenAI Realtime for real-time
            config = {
                "tts_provider": DEFAULT_TTS_PROVIDER,
                "tts_model": TTS_PROVIDERS[DEFAULT_TTS_PROVIDER]["default_model"],
                "stt_provider": DEFAULT_STT_PROVIDER,
                "stt_model": STT_PROVIDERS[DEFAULT_STT_PROVIDER]["default_model"],
                "llm_provider": DEFAULT_LLM_PROVIDER,
                "llm_model": LLM_PROVIDERS[DEFAULT_LLM_PROVIDER]["default_model"],
                "evaluation_id": evaluation_id,
                "application_id": application_id,
                "interview_id": interview_id,
                "job_offer_id": job_offer_id,
                "candidate_cv_text": candidate_cv_text,
                "candidate_name": candidate_name_from_cv if 'candidate_name_from_cv' in locals() and candidate_name_from_cv else None,
                "interview_duration_minutes": interview_duration_minutes
            }
            session_configs[conversation_id] = config

            # Track interview start time for time limit
            interview_start_times[conversation_id] = time.time()

            logger.info(f"🚀 New interview started: {conversation_id}")
            logger.info(f"⏱️ Time limit: {interview_duration_minutes} minutes")

            # ============================================================
            # OPENAI REALTIME MODE — native audio-in/audio-out
            # ============================================================
            if True:  # Always use OpenAI Realtime for real-time interviews
                logger.info("🎙️ OPENAI REALTIME MODE — real-time audio conversation")
                from backend.services.openai_realtime import OpenAIRealtimeSession
                from backend.config import OPENAI_API_KEY, OPENAI_REALTIME_MODEL, OPENAI_REALTIME_VOICE, build_interviewer_system_prompt

                # Build system prompt with full interview context
                live_system_prompt = build_interviewer_system_prompt(
                    job_title=job_offer.title if job_offer else None,
                    job_offer_description=job_offer.get_full_description() if job_offer else None,
                    candidate_cv_text=candidate_cv_text,
                    required_languages=required_languages,
                    interview_start_language=interview_start_language,
                    confirmed_candidate_name=candidate_name_from_cv if 'candidate_name_from_cv' in locals() else None,
                    time_remaining_minutes=float(interview_duration_minutes),
                    total_interview_minutes=float(interview_duration_minutes),
                    custom_questions=custom_questions,
                    evaluation_weights=evaluation_weights,
                )
                # Parse required languages for multi-language support
                _req_langs_list = []
                if required_languages:
                    try:
                        _req_langs_list = json.loads(required_languages) if required_languages else []
                    except Exception:
                        _req_langs_list = []
                # Parse custom questions count for end-interview guard
                _custom_questions_count = 0
                if custom_questions:
                    try:
                        _cq_list = json.loads(custom_questions) if custom_questions else []
                        _custom_questions_count = len(_cq_list) if isinstance(_cq_list, list) else 0
                    except Exception:
                        pass

                # Add language enforcement at the top (Google best practice for OpenAI Realtime)
                _enforce_lang = interview_start_language or 'the specified language'
                if len(_req_langs_list) > 1:
                    # Multi-language: start in one language, switch later as instructed
                    live_system_prompt = f"""START BY RESPONDING IN {_enforce_lang.upper()}. YOU MUST RESPOND UNMISTAKABLY IN {_enforce_lang.upper()} UNTIL THE SYSTEM INSTRUCTS YOU TO SWITCH LANGUAGES.

""" + live_system_prompt
                else:
                    live_system_prompt = f"""RESPOND IN {_enforce_lang.upper()}. YOU MUST RESPOND UNMISTAKABLY IN {_enforce_lang.upper()}.

""" + live_system_prompt

                # Add live-specific instructions
                live_system_prompt += f"""

LIVE CONVERSATION RULES:
- YOUR IDENTITY: You are Granit, a friendly virtual interview assistant from Granitalent. When greeting the candidate, introduce yourself by name: "Hi, I'm Granit, your virtual interview assistant from Granitalent."
- Start by greeting the candidate warmly in {interview_start_language or 'the specified language'}, introduce yourself as Granit, mention the position they're interviewing for, then ask your first question.
- Speak naturally and conversationally — this is a real-time voice call.
- Keep responses SHORT (1-3 sentences). Do not monologue.
- LANGUAGE: You MUST speak in {interview_start_language or 'the specified language'}. The candidate must answer in the same language. If they answer in a different language, politely ask them to switch to the required language.
- MOST IMPORTANT RULE — ONE QUESTION, THEN STOP: Each of your turns must contain at most ONE question. After asking a question, you MUST STOP TALKING and wait silently for the candidate to answer. NEVER ask two questions in the same turn. NEVER follow a question with another question, a comment, a language switch, or a farewell. The strict flow is: ask ONE question → STOP → candidate speaks → only THEN respond.
- BACKGROUND NOISE: If you hear only silence, clicks, typing, or background noise without actual speech, do NOT treat it as a response. Wait patiently. Only proceed when the candidate says actual words. If unclear, say "Could you repeat that?" instead of moving on.
- MANDATORY QUESTIONS FIRST: If the recruiter has programmed specific questions (listed in MANDATORY QUESTIONS section), you MUST ask ALL of them FIRST before asking any of your own questions. Do NOT skip any. Do NOT mix in your own questions until all mandatory questions have been asked.
- ENDING THE INTERVIEW: Do NOT end the interview on your own. The system manages timing. Just keep asking questions and waiting for answers. When the system tells you it is time to end, FIRST wait for the candidate to finish answering, THEN say a warm goodbye, THEN call end_interview.
- CRITICAL — NEVER COMBINE A QUESTION WITH A FAREWELL: If you are about to end the interview, do NOT ask a question and say goodbye in the same turn. Either ask a question and wait for the answer, OR say goodbye. Never both.
- If the candidate explicitly asks to end the interview, you may say goodbye and call end_interview.
- You MUST call end_interview after your farewell — this is how the system knows the interview is over.
- Do NOT wait for the candidate to respond after your farewell — call end_interview right away.
- NEVER ask the candidate if they have any questions. This is a one-way evaluation interview."""

                # Add multi-language instructions if applicable
                if len(_req_langs_list) > 1:
                    live_system_prompt += f"""

MULTI-LANGUAGE INTERVIEW — MANDATORY:
- This interview REQUIRES testing the candidate in ALL of these languages: {', '.join(_req_langs_list)}.
- Start in {interview_start_language or _req_langs_list[0]}.
- LANGUAGE SWITCHING: The system will tell you when to switch. When you receive a switch instruction:
  1. Your ENTIRE next turn must be in the NEW language ONLY. Zero words in the old language.
  2. Say a short transition phrase in the new language (e.g., "Continuons en français" or "Let's continue in English").
  3. Ask ONE question in the new language. Then STOP and WAIT.
- CRITICAL: When switching, do NOT acknowledge the previous answer in the old language. Just switch cleanly to the new language.
- CRITICAL: ALWAYS wait for the candidate to fully answer before switching. Flow: ask → WAIT → hear answer → THEN switch.
- Each turn must be ENTIRELY in ONE language. Never mix two languages in the same response.
- Ask only ONE question per turn, then STOP and wait for the answer.
- DO NOT end the interview until the system tells you to.
- DO NOT anticipate switches or mention upcoming language changes."""

                live_model = OPENAI_REALTIME_MODEL
                live_voice = init_data.get("voice", OPENAI_REALTIME_VOICE)

                # Determine language code for transcription
                live_lang_code = get_language_code(interview_start_language or "") or "en"
                session = OpenAIRealtimeSession(
                    api_key=OPENAI_API_KEY,
                    model=live_model,
                    system_prompt=live_system_prompt,
                    voice=live_voice,
                    language=live_lang_code,
                )

                ws_lock = asyncio.Lock()
                output_transcript_buffer = []
                live_concluded = False
                interview_ending = False  # Set when end_interview is called, live_concluded set after turnComplete
                interview_ending_timer = [None]  # Fallback timer to force live_concluded
                user_is_speaking = False
                ai_is_speaking = False  # True while AI audio is being generated (prevents echo detection)
                echo_cooldown_until = [0.0]  # timestamp until which echo suppression is active (post-turn playback delay)
                # Audio capture: collect all candidate PCM chunks for combined recording + per-turn audio
                all_input_audio_chunks = []    # full recording (base64 PCM chunks)
                turn_input_audio_chunks = []   # per-turn buffer for audio recording
                per_turn_audio_data = []       # list of (turn_index, pcm_bytes) for per-answer audio
                turn_counter = [0]             # mutable counter for turn numbering
                # Full interview recording timeline: interleaved candidate (16kHz) + AI (24kHz) audio
                recording_timeline = []        # list of ("input"|"output", base64_pcm_chunk)
                # Per-turn transcript accumulator: OpenAI sends complete transcriptions per turn,
                # but we accumulate in case of multiple speech segments before AI responds
                current_turn_parts = []        # list of transcript strings
                finalize_lock = asyncio.Lock() # prevent concurrent finalization

                # Track the current expected language
                current_expected_language = interview_start_language or "French"
                current_language_code = live_lang_code  # ISO code like "fr", "en"

                # Multi-language: track AI question count per language for switch timing
                ai_turn_count = [0]                  # total AI turns
                questions_in_current_lang = [0]      # questions in current language
                switch_sent = [False]                 # whether we already sent a switch command this language

                async def finalize_user_transcript(is_turn_seal: bool = False):
                    """Seal the current user turn into the conversation.

                    With OpenAI Realtime, transcription comes directly from the API via
                    on_live_input_transcription (gpt-4o-transcribe). This function just
                    combines current_turn_parts into one conversation message and saves
                    accumulated audio to per_turn_audio_data for recording."""
                    nonlocal user_is_speaking
                    async with finalize_lock:
                        if is_turn_seal and current_turn_parts:
                            full_text = " ".join(current_turn_parts)
                            current_turn_parts.clear()
                            turn_idx = turn_counter[0]
                            turn_counter[0] += 1
                            # Combine audio chunks into per-turn recording
                            has_audio = False
                            if turn_input_audio_chunks:
                                import base64 as _b64
                                raw_parts = []
                                for chunk in turn_input_audio_chunks:
                                    try:
                                        raw_parts.append(_b64.b64decode(chunk))
                                    except Exception:
                                        pass
                                turn_pcm = b"".join(raw_parts) if raw_parts else b""
                                turn_input_audio_chunks.clear()
                                if len(turn_pcm) >= 9600:
                                    per_turn_audio_data.append((turn_idx, turn_pcm))
                                    has_audio = True
                            conversation.add_message("candidate", full_text, audio_turn=turn_idx if has_audio else None)
                            logger.info(f"📝 Sealed user turn: '{full_text[:100]}' (turn {turn_idx})")
                        elif is_turn_seal:
                            current_turn_parts.clear()
                            turn_input_audio_chunks.clear()
                        user_is_speaking = False


                async def on_live_audio(pcm_base64: str):
                    nonlocal ai_is_speaking
                    ai_is_speaking = True
                    # Don't play or record AI audio after end_interview was called
                    # (AI may generate a duplicate farewell from the function call ack)
                    if interview_ending:
                        return
                    # Capture AI audio for full interview recording
                    recording_timeline.append(("output", pcm_base64))
                    async with ws_lock:
                        try:
                            await websocket.send_json({
                                "type": "live_audio",
                                "audio": pcm_base64,
                            })
                        except Exception:
                            pass

                async def on_live_text(text: str):
                    pass

                async def on_live_output_transcription(text: str):
                    """Transcription of what the AI said."""
                    output_transcript_buffer.append(text)

                def _is_noise_transcription(text: str) -> bool:
                    """Detect ONLY the most obvious Whisper hallucinations (wrong-script gibberish).

                    IMPORTANT: We intentionally keep ALL real candidate speech — even hesitations,
                    filler words, repetitions, or errors — because the transcript is used for
                    HR analysis later. Only filter out things that are clearly NOT speech."""
                    import unicodedata as _ud
                    import re as _re_n

                    t = text.strip()
                    t_lower = t.lower()

                    # 1. Bracket-enclosed descriptors: [silence], (bruit de fond), etc.
                    #    These are Whisper's own annotations, never real speech.
                    if _re_n.match(r'^[\[\(].*[\]\)]$', t_lower):
                        return True

                    # 2. Well-known Whisper subtitle hallucinations (these are NEVER real speech)
                    _subtitle_hallucinations = {
                        "sous-titres réalisés para la communauté d'amara.org",
                        "sous-titrage", "transcrit par", "translated by",
                        "thanks for watching", "thank you for watching",
                        "thanks for watching.", "thank you for watching.",
                        "merci d'avoir regardé",
                    }
                    if t_lower in _subtitle_hallucinations:
                        return True

                    # 3. Wrong-script detection: CJK/Hangul/Thai characters in a Latin-script interview.
                    #    This is the main Whisper noise hallucination — it "hears" noise and outputs
                    #    text in completely unrelated scripts.
                    _expected_scripts = set()
                    for lang in _req_langs_list or []:
                        lang_lower = lang.lower()
                        if lang_lower in ("arabic",):
                            _expected_scripts.add("ARABIC")
                        elif lang_lower in ("chinese", "mandarin", "cantonese"):
                            _expected_scripts.update({"CJK", "HAN"})
                        elif lang_lower in ("japanese",):
                            _expected_scripts.update({"CJK", "HAN", "HIRAGANA", "KATAKANA"})
                        elif lang_lower in ("korean",):
                            _expected_scripts.update({"HANGUL"})
                        elif lang_lower in ("thai",):
                            _expected_scripts.add("THAI")
                        elif lang_lower in ("hindi",):
                            _expected_scripts.add("DEVANAGARI")
                        elif lang_lower in ("russian", "ukrainian"):
                            _expected_scripts.add("CYRILLIC")
                        else:
                            _expected_scripts.add("LATIN")
                    if not _expected_scripts:
                        _expected_scripts.add("LATIN")

                    # Count characters by script category
                    _script_counts = {}
                    _total_alpha = 0
                    for ch in t:
                        if not ch.isalpha():
                            continue
                        _total_alpha += 1
                        try:
                            name = _ud.name(ch, "")
                        except ValueError:
                            name = ""
                        script = "OTHER"
                        if "CJK" in name or "HAN" in name:
                            script = "CJK"
                        elif "HANGUL" in name:
                            script = "HANGUL"
                        elif "HIRAGANA" in name or "KATAKANA" in name:
                            script = "CJK"
                        elif "ARABIC" in name:
                            script = "ARABIC"
                        elif "CYRILLIC" in name:
                            script = "CYRILLIC"
                        elif "THAI" in name:
                            script = "THAI"
                        elif "DEVANAGARI" in name:
                            script = "DEVANAGARI"
                        elif "LATIN" in name:
                            script = "LATIN"
                        _script_counts[script] = _script_counts.get(script, 0) + 1

                    # If >50% of alpha chars are in a completely unexpected script, it's noise
                    # (higher threshold than before — we want to be very conservative)
                    if _total_alpha > 3:
                        for script, count in _script_counts.items():
                            if script == "OTHER":
                                continue
                            if script not in _expected_scripts and count / _total_alpha > 0.5:
                                logger.info(f"🔇 Noise: unexpected script '{script}' ({count}/{_total_alpha} chars): '{t[:60]}'")
                                return True

                    return False

                async def on_live_input_transcription(text: str):
                    """OpenAI's transcription of user speech (complete per-turn transcript).

                    OpenAI Realtime sends conversation.item.input_audio_transcription.completed
                    with a complete transcription after semantic VAD detects end of speech.

                    IMPORTANT: No ai_is_speaking or echo_cooldown check here. OpenAI's
                    transcription is of the BUFFERED USER INPUT only — it cannot contain echo."""
                    nonlocal user_is_speaking
                    if not text or not text.strip():
                        return

                    cleaned = text.strip()
                    if len(cleaned) < 2:
                        return

                    # Comprehensive noise detection
                    if _is_noise_transcription(cleaned):
                        logger.debug(f"Skipping noise transcription: '{cleaned[:60]}'")
                        return

                    current_turn_parts.append(cleaned)
                    user_is_speaking = False  # User finished speaking (transcription is post-VAD)
                    logger.info(f"📝 User transcription received: '{cleaned[:80]}' (parts so far: {len(current_turn_parts)})")

                    # Send to frontend
                    full_so_far = " ".join(current_turn_parts)
                    async with ws_lock:
                        try:
                            await websocket.send_json({
                                "type": "live_user_transcript",
                                "text": full_so_far,
                            })
                        except Exception:
                            pass

                async def on_live_interview_end(reason: str):
                    """Called when OpenAI invokes the end_interview function.
                    Returns False to reject if not enough questions asked or untested languages remain.
                    Uses two-phase shutdown: sets interview_ending first, then live_concluded
                    only after the next turnComplete processes the last user answer."""
                    nonlocal interview_ending
                    logger.info(f"🔔 end_interview called: reason={reason}, ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()}, q_in_lang={questions_in_current_lang[0]}")

                    # Guard 1: reject premature ending — need enough AI turns
                    # Minimum is max(4, custom_questions + 2) to ensure all custom questions are asked
                    _min_turns = max(4, _custom_questions_count + 2)  # +2 for greeting + at least 1 organic question
                    if reason != "candidate_requested" and ai_turn_count[0] < _min_turns:
                        _remaining_q = _min_turns - ai_turn_count[0]
                        logger.warning(f"🚫 Rejected end_interview: only {ai_turn_count[0]} turns (minimum {_min_turns}, custom_q={_custom_questions_count})")
                        return {"reason": (
                            "REJECTED: The interview is not finished. You have only asked "
                            f"{ai_turn_count[0]} question(s) — you need at least {_remaining_q} more. "
                            + (f"You have {_custom_questions_count} mandatory questions from the recruiter that MUST all be asked. " if _custom_questions_count > 0 else "")
                            + "Continue asking questions. Do NOT attempt to end the interview again until you have asked more questions."
                        )}

                    # Guard 2: reject if untested languages remain in multi-language interviews
                    if _req_langs_list and len(_req_langs_list) > 1 and reason != "candidate_requested":
                        untested = [l for l in _req_langs_list if l not in conversation.get_tested_languages()]
                        if untested:
                            next_lang = untested[0]
                            logger.warning(f"🚫 Rejected end_interview: untested languages remain: {untested}")
                            # Update language tracking for the forced switch
                            injected_language_target[0] = next_lang
                            switch_sent[0] = True
                            logger.info(f"🔄 Forcing language switch to {next_lang} via rejection response")
                            return {"reason": (
                                f"REJECTED: You have NOT yet tested the candidate in {next_lang}. "
                                f"This is a MANDATORY multi-language interview requiring ALL of: {', '.join(_req_langs_list)}. "
                                f"You MUST switch to {next_lang} NOW. "
                                f"In your next response: announce IN {next_lang} that you will continue in {next_lang}, "
                                f"then ask ONE question entirely in {next_lang}. "
                                f"Do NOT end the interview. Do NOT say goodbye. Just switch languages and ask a question."
                            )}

                    logger.info(f"OpenAI Realtime: end_interview accepted (reason: {reason})")
                    interview_ending = True
                    # DON'T set live_concluded here — wait for turnComplete to finalize last answer
                    # Notify frontend that the AI ended the interview
                    async with ws_lock:
                        try:
                            await websocket.send_json({
                                "type": "interview_ended",
                                "reason": reason,
                            })
                        except Exception:
                            pass
                    # Fallback: force live_concluded after 8 seconds if turnComplete never arrives
                    async def _force_conclude():
                        nonlocal live_concluded
                        await asyncio.sleep(8)
                        if not live_concluded:
                            logger.warning("⚠️ Forcing live_concluded after 8s timeout (turnComplete didn't arrive)")
                            live_concluded = True
                    interview_ending_timer[0] = asyncio.create_task(_force_conclude())

                def _detect_language_of_text(text: str, candidate_languages: list) -> str:
                    """Detect which of the candidate languages a text is written in.
                    Uses simple heuristic: check for language-specific common words/patterns."""
                    text_lower = text.lower()
                    # Language detection via common function words
                    lang_markers = {
                        "French": ["je ", "vous ", "nous ", "est ", "les ", "des ", "une ", "dans ", "pour ", "avec ", "très ", "que ", "qui ", "c'est", "merci", "bonjour", "comment", "parlez", "avez"],
                        "English": ["the ", "is ", "are ", "you ", "your ", "have ", "what ", "how ", "this ", "that ", "with ", "would ", "could ", "about ", "thank ", "hello", "please", "great"],
                        "Arabic": ["في ", "من ", "على ", "إلى ", "هل ", "ما ", "كيف ", "هذا ", "أن ", "لا ", "نعم", "مرحبا", "شكرا"],
                        "Spanish": ["el ", "la ", "los ", "las ", "es ", "son ", "usted ", "cómo ", "qué ", "por ", "para ", "con ", "muy ", "bien ", "gracias", "hola"],
                        "German": ["der ", "die ", "das ", "ist ", "sind ", "haben ", "wie ", "was ", "für ", "mit ", "sehr ", "gut ", "danke", "hallo", "bitte"],
                        "Italian": ["il ", "la ", "le ", "è ", "sono ", "come ", "che ", "per ", "con ", "molto ", "bene ", "grazie", "buongiorno"],
                        "Portuguese": ["o ", "a ", "os ", "as ", "é ", "são ", "como ", "que ", "para ", "com ", "muito ", "bem ", "obrigado"],
                        "Dutch": ["de ", "het ", "is ", "zijn ", "hoe ", "wat ", "voor ", "met ", "heel ", "goed ", "dank", "hallo"],
                        "Turkish": ["bir ", "bu ", "ve ", "için ", "ile ", "nasıl ", "ne ", "çok ", "iyi ", "teşekkür", "merhaba"],
                        "Chinese": ["的", "是", "在", "了", "不", "有", "这", "我", "你", "他"],
                        "Japanese": ["の", "は", "が", "を", "に", "で", "と", "も", "です", "ます"],
                        "Korean": ["는", "은", "이", "가", "를", "에", "의", "도", "입니다"],
                    }
                    scores = {}
                    for lang in candidate_languages:
                        markers = lang_markers.get(lang, [])
                        if not markers:
                            continue
                        score = sum(1 for m in markers if m in text_lower)
                        scores[lang] = score
                    if scores:
                        best = max(scores, key=scores.get)
                        if scores[best] >= 2:  # need at least 2 markers
                            return best
                    return None

                # Language switch state
                switch_context_injected = [False]  # True after we buffered a switch hint via send_context
                switch_context_target = [None]     # which language the hint targets
                injected_language_target = [None]   # target language from forced injection, for STT code update
                switch_turn_in_progress = [False]   # True during forced injection response (suppress echo)

                async def _hint_language_switch(target_lang: str):
                    """Buffer a language switch instruction into the conversation context WITHOUT forcing a response.

                    Uses send_context so the instruction is buffered until the candidate next speaks
                    and VAD completes the turn. The model processes the candidate's answer + our hint
                    together, producing ONE natural response that acknowledges the answer AND switches
                    language. No interruption.
                    """
                    try:
                        switch_context_injected[0] = True
                        switch_context_target[0] = target_lang
                        await session.send_context(
                            f"[SYSTEM — LANGUAGE SWITCH] "
                            f"After the candidate finishes their current answer, switch entirely to {target_lang}. "
                            f"Your ENTIRE next response must be in {target_lang} only — do NOT use the current language at all. "
                            f"Say a brief transition like "
                            + ("\"Let's continue in English.\" " if target_lang == "English" else
                               "\"Continuons en français.\" " if target_lang == "French" else
                               f"a short phrase in {target_lang}. ")
                            + f"then ask ONE question in {target_lang}. "
                            f"IMPORTANT: Say only ONE question, then STOP and WAIT for the candidate to answer."
                        )
                        logger.info(f"🔄 Language switch HINT buffered (turnComplete=false): → {target_lang}")
                    except Exception as e:
                        logger.error(f"Failed to buffer language switch hint: {e}")

                async def _force_language_switch(target_lang: str):
                    """Force an immediate language switch by sending turnComplete=true.

                    Used as a fallback when the hint approach didn't work (model ignored the hint).
                    This WILL interrupt the current flow and force an immediate response.
                    """
                    nonlocal user_is_speaking
                    try:
                        injected_language_target[0] = target_lang
                        switch_turn_in_progress[0] = True
                        turn_input_audio_chunks.clear()
                        current_turn_parts.clear()
                        user_is_speaking = False
                        await session.send_text(
                            f"[SYSTEM — IMMEDIATE LANGUAGE SWITCH] "
                            f"Switch to {target_lang} NOW. "
                            f"Your ENTIRE response must be in {target_lang} only — zero words in any other language. "
                            f"Say a brief transition like "
                            + ("\"Let's continue in English.\" " if target_lang == "English" else
                               "\"Continuons en français.\" " if target_lang == "French" else
                               f"a short phrase in {target_lang} ")
                            + f"then ask ONE question in {target_lang}. "
                            f"IMPORTANT: Say only ONE question, then STOP and WAIT for the candidate to answer."
                        )
                        logger.info(f"🔄 Language switch FORCED (turnComplete=true): → {target_lang}")
                    except Exception as e:
                        logger.error(f"Failed to force language switch: {e}")

                end_instruction_sent = [False]

                async def _inject_end_instruction():
                    """Tell the AI it's time to wrap up — uses send_context so it doesn't
                    interrupt the current turn. The AI will process this on its next response."""
                    if end_instruction_sent[0] or interview_ending:
                        return
                    end_instruction_sent[0] = True
                    try:
                        await session.send_context(
                            "[SYSTEM INSTRUCTION — TIME TO END] "
                            "You have now asked enough questions in all required languages. "
                            "AFTER the candidate finishes answering your current question, "
                            "thank them warmly for their time, say a brief farewell, "
                            "then call the end_interview function. "
                            "CRITICAL: Do NOT ask another question. Do NOT combine a question with a farewell. "
                            "Wait for the candidate's answer first, THEN say goodbye in a separate turn."
                        )
                        logger.info("📩 End instruction buffered (send_context) to OpenAI Realtime")
                    except Exception as e:
                        logger.error(f"Failed to inject end instruction: {e}")

                async def on_live_turn_complete():
                    nonlocal current_expected_language, current_language_code, live_concluded, ai_is_speaking, user_is_speaking
                    ai_is_speaking = False
                    # Post-turn echo cooldown: speakers may still be playing buffered audio
                    import time as _time_mod
                    _cooldown_s = 2.5 if switch_turn_in_progress[0] else 2.0
                    echo_cooldown_until[0] = _time_mod.time() + _cooldown_s
                    # AI finished speaking — seal the user's previous turn transcript
                    # Skip if the current turn was a switch response (audio is echo/noise)
                    _ai_text_preview = " ".join(output_transcript_buffer).strip()
                    if not switch_turn_in_progress[0]:
                        # Only seal if AI produced real output (not a micro-turn)
                        _should_seal = len(_ai_text_preview) >= 5 or interview_ending
                        await finalize_user_transcript(is_turn_seal=_should_seal)
                    else:
                        # Discard any audio/transcripts that accumulated during the switch announcement
                        turn_input_audio_chunks.clear()
                        current_turn_parts.clear()
                        user_is_speaking = False
                    # Use output transcription buffer for AI text
                    full_text = " ".join(output_transcript_buffer).strip()
                    output_transcript_buffer.clear()

                    # If interview is ending (end_interview was called), set live_concluded NOW
                    # This ensures finalize_user_transcript() ran BEFORE we exit the main loop
                    if interview_ending:
                        if full_text:
                            conversation.add_message("interviewer", full_text)
                        # Cancel the fallback timer
                        if interview_ending_timer[0]:
                            interview_ending_timer[0].cancel()
                            interview_ending_timer[0] = None
                        logger.info("✅ Final turnComplete processed — setting live_concluded")
                        live_concluded = True
                        async with ws_lock:
                            try:
                                await websocket.send_json({
                                    "type": "live_turn_complete",
                                    "text": full_text or "",
                                })
                            except Exception:
                                pass
                        return

                    if full_text:
                        # Check if this is a forced switch turn (response to send_text injection)
                        is_forced_switch_turn = switch_turn_in_progress[0]
                        switch_turn_in_progress[0] = False

                        conversation.add_message("interviewer", full_text)
                        ai_turn_count[0] += 1

                        # Track which language the AI is speaking & detect switches
                        if _req_langs_list and len(_req_langs_list) > 1:
                            # If we force-injected a language switch, apply the target language
                            if injected_language_target[0]:
                                forced_lang = injected_language_target[0]
                                injected_language_target[0] = None
                                if forced_lang != current_expected_language:
                                    current_expected_language = forced_lang
                                    current_language_code = get_language_code(forced_lang) or current_language_code
                                    conversation.add_tested_language(forced_lang)
                                    conversation.set_current_language(forced_lang)
                                    questions_in_current_lang[0] = 1
                                    switch_sent[0] = False
                                    switch_context_injected[0] = False
                                    switch_context_target[0] = None
                                    logger.info(f"🌐 Language force-switched to: {forced_lang} ({current_language_code})")
                                else:
                                    questions_in_current_lang[0] += 1
                            else:
                                # Detect language organically from the AI's text
                                detected_lang = _detect_language_of_text(full_text, _req_langs_list)
                                if detected_lang and detected_lang != current_expected_language:
                                    # AI switched language (either from our hint or organically)
                                    current_expected_language = detected_lang
                                    current_language_code = get_language_code(detected_lang) or current_language_code
                                    conversation.add_tested_language(detected_lang)
                                    conversation.set_current_language(detected_lang)
                                    questions_in_current_lang[0] = 1
                                    switch_sent[0] = False
                                    # Clear the hint state — switch was successful
                                    switch_context_injected[0] = False
                                    switch_context_target[0] = None
                                    logger.info(f"🌐 Language switched to: {detected_lang} ({current_language_code})")
                                else:
                                    # Same language — increment counter and mark tested
                                    questions_in_current_lang[0] += 1
                                    conversation.add_tested_language(current_expected_language)

                            # --- LANGUAGE SWITCH LOGIC ---
                            # Strategy: At Q3, buffer a hint so the model incorporates the switch
                            # into its NEXT natural response. If ignored by Q5+, force it.
                            untested = [l for l in _req_langs_list if l not in conversation.get_tested_languages()]

                            if untested and not switch_sent[0] and not is_forced_switch_turn:
                                if questions_in_current_lang[0] >= 3:
                                    # Buffer the switch hint — does NOT force a response
                                    # Threshold is 3 because turn 1 is the greeting/introduction
                                    next_lang = untested[0]
                                    switch_sent[0] = True
                                    logger.info(f"🔄 Buffering language switch hint: {current_expected_language} → {next_lang} (after {questions_in_current_lang[0]} questions)")
                                    asyncio.create_task(_hint_language_switch(next_lang))

                            elif untested and switch_context_injected[0] and questions_in_current_lang[0] >= 5:
                                # Hint was ignored for 2+ turns — force the switch
                                next_lang = switch_context_target[0] or untested[0]
                                logger.warning(f"⚠️ Hint was ignored ({questions_in_current_lang[0]} questions in {current_expected_language}, threshold 5), forcing switch → {next_lang}")
                                switch_context_injected[0] = False
                                switch_context_target[0] = None
                                asyncio.create_task(_force_language_switch(next_lang))

                            # All languages tested and enough questions — tell AI to wrap up
                            _min_before_end = max(5, _custom_questions_count + 2)
                            if not untested and ai_turn_count[0] >= _min_before_end and questions_in_current_lang[0] >= 2 and not interview_ending:
                                logger.info(f"✅ All languages tested, {ai_turn_count[0]} questions asked (min {_min_before_end}) — injecting end instruction")
                                asyncio.create_task(_inject_end_instruction())

                        async with ws_lock:
                            try:
                                await websocket.send_json({
                                    "type": "live_turn_complete",
                                    "text": full_text,
                                })
                            except Exception:
                                pass

                async def on_live_interrupted():
                    """User started speaking (speech_started event from OpenAI).
                    Fires both when user interrupts the AI AND during normal turn-taking."""
                    nonlocal ai_is_speaking, user_is_speaking
                    was_ai_speaking = ai_is_speaking
                    ai_is_speaking = False
                    user_is_speaking = True
                    if was_ai_speaking:
                        # Actual interruption — apply echo cooldown
                        import time as _time_mod
                        echo_cooldown_until[0] = _time_mod.time() + 1.0
                        async with ws_lock:
                            try:
                                await websocket.send_json({"type": "live_interrupted"})
                            except Exception:
                                pass
                    # Always signal "user speaking" to frontend
                    async with ws_lock:
                        try:
                            await websocket.send_json({"type": "user_speaking", "speaking": True})
                        except Exception:
                            pass

                session.on_audio(on_live_audio)
                session.on_text(on_live_text)
                session.on_turn_complete(on_live_turn_complete)
                session.on_interrupted(on_live_interrupted)
                session.on_input_transcription(on_live_input_transcription)
                session.on_output_transcription(on_live_output_transcription)
                session.on_interview_end(on_live_interview_end)

                try:
                    await session.connect()

                    await websocket.send_json({
                        "type": "live_ready",
                        "conversation_id": conversation_id,
                        "time_limit_minutes": interview_duration_minutes,
                    })

                    # Kick off the conversation — the model won't speak first on its own
                    candidate_name = conversation.cv_candidate_name or "the candidate"
                    start_language = interview_start_language or "English"
                    await session.send_text(
                        f"The interview has just started. Speak ONLY in {start_language}. "
                        f"Greet {candidate_name} warmly in {start_language} and ask your first question in {start_language}."
                    )
                    logger.info("📢 Sent initial prompt to OpenAI Realtime to start talking")

                    reconnect_attempts = [0]
                    max_reconnects = 2

                    # Live message loop — exits when AI concludes, user ends, or session drops
                    while not live_concluded:
                        if not session.connected:
                            # Check if we should attempt reconnection
                            untested_langs = [l for l in _req_langs_list if l not in conversation.get_tested_languages()] if _req_langs_list and len(_req_langs_list) > 1 else []
                            if not interview_ending and untested_langs and reconnect_attempts[0] < max_reconnects:
                                reconnect_attempts[0] += 1
                                logger.warning(f"⚠️ OpenAI Realtime disconnected with untested languages {untested_langs} — attempting reconnect ({reconnect_attempts[0]}/{max_reconnects})")
                                try:
                                    await session.close()
                                    # Rebuild session with existing conversation context
                                    history_summary = conversation.get_history_for_llm()
                                    context_lines = []
                                    for msg in history_summary[-6:]:  # last 6 messages for context
                                        role = "Interviewer" if msg["role"] == "interviewer" else "Candidate"
                                        context_lines.append(f"{role}: {msg['content'][:200]}")
                                    context_text = "\n".join(context_lines)

                                    session = OpenAIRealtimeSession(
                                        api_key=OPENAI_API_KEY,
                                        model=live_model,
                                        system_prompt=live_system_prompt,
                                        voice=live_voice,
                                        language=live_lang_code,
                                    )
                                    # Re-register callbacks
                                    session.on_audio(on_live_audio)
                                    session.on_text(on_live_text)
                                    session.on_turn_complete(on_live_turn_complete)
                                    session.on_interrupted(on_live_interrupted)
                                    session.on_input_transcription(on_live_input_transcription)
                                    session.on_output_transcription(on_live_output_transcription)
                                    session.on_interview_end(on_live_interview_end)
                                    await session.connect()

                                    # Resume with context and language switch
                                    next_lang = untested_langs[0]
                                    await session.send_text(
                                        f"[SYSTEM INSTRUCTION] You are resuming an ongoing interview. "
                                        f"Here is the recent conversation:\n{context_text}\n\n"
                                        f"Continue the interview naturally. Switch to {next_lang} now. "
                                        f"Briefly acknowledge the reconnection if needed, then ask a question in {next_lang}."
                                    )
                                    # Update language tracking
                                    current_expected_language = next_lang
                                    current_language_code = get_language_code(next_lang) or current_language_code
                                    questions_in_current_lang[0] = 0
                                    switch_sent[0] = False
                                    switch_context_injected[0] = False
                                    switch_context_target[0] = None
                                    logger.info(f"✅ OpenAI Realtime reconnected successfully — switching to {next_lang}")
                                    async with ws_lock:
                                        try:
                                            await websocket.send_json({"type": "live_reconnected"})
                                        except Exception:
                                            pass
                                    continue
                                except Exception as reconn_err:
                                    logger.error(f"❌ OpenAI Realtime reconnect failed: {reconn_err}")
                                    break
                            else:
                                logger.warning(f"⚠️ OpenAI Realtime session disconnected — exiting loop (ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()}, ending={interview_ending})")
                                break
                        try:
                            message = await asyncio.wait_for(websocket.receive(), timeout=1.0)
                        except asyncio.TimeoutError:
                            # Check if interview time has expired
                            elapsed = (time.time() - interview_start_times.get(conversation_id, time.time())) / 60
                            if elapsed >= interview_duration_minutes + 1:
                                logger.info(f"⏰ Interview time limit exceeded ({elapsed:.0f} min) — forcing exit (ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()})")
                                break
                            # Time-based language switch: if past halfway and untested languages remain
                            if _req_langs_list and len(_req_langs_list) > 1 and not switch_sent[0]:
                                halfway = interview_duration_minutes / 2
                                if elapsed >= halfway:
                                    untested = [l for l in _req_langs_list if l not in conversation.get_tested_languages()]
                                    if untested:
                                        next_lang = untested[0]
                                        switch_sent[0] = True
                                        # Time pressure — use hint first, force will kick in at Q5+
                                        asyncio.create_task(_hint_language_switch(next_lang))
                                        logger.info(f"⏰ Past halfway ({elapsed:.1f}/{interview_duration_minutes} min), hinted switch to {next_lang}")
                            continue
                        except Exception as recv_err:
                            logger.warning(f"⚠️ WebSocket receive error: {recv_err} (ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()})")
                            break
                        if "text" in message:
                            data = json.loads(message["text"])
                            msg_type = data.get("type")

                            if msg_type == "live_audio":
                                all_input_audio_chunks.append(data["audio"])
                                recording_timeline.append(("input", data["audio"]))
                                await session.send_audio(data["audio"])
                                # Buffer audio for per-turn recording (skip while AI is speaking to avoid echo)
                                if not ai_is_speaking:
                                    turn_input_audio_chunks.append(data["audio"])
                            elif msg_type == "end_interview":
                                logger.info(f"👤 User ended OpenAI Realtime interview (ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()})")
                                break
                        elif "bytes" in message:
                            pass
                except Exception as e:
                    err_str = str(e).lower()
                    if "disconnect" in err_str or "closed" in err_str:
                        logger.info(f"📡 Client disconnected from OpenAI Realtime (ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()}, ending={interview_ending})")
                    else:
                        logger.error(f"OpenAI Realtime error: {e} (ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()})")
                        try:
                            await websocket.send_json({
                                "type": "error",
                                "message": f"Real-time voice error: {str(e)}. Try the Classic mode instead.",
                            })
                        except Exception:
                            pass
                finally:
                    logger.info(f"📋 Interview session ending: live_concluded={live_concluded}, interview_ending={interview_ending}, ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()}, history_len={len(conversation.get_history_for_llm()) if conversation else 0}")
                    # Cancel the fallback interview_ending timer if still running
                    if interview_ending_timer[0]:
                        interview_ending_timer[0].cancel()
                        interview_ending_timer[0] = None

                    # Give the receive loop a moment to process any final turnComplete
                    # (so finalize_user_transcript runs via on_live_turn_complete for the last answer)
                    if interview_ending and session.connected:
                        logger.info("⏳ Waiting for final OpenAI messages before closing...")
                        await asyncio.sleep(2)

                    # Finalize any pending user transcript BEFORE closing the session
                    await finalize_user_transcript(is_turn_seal=True)

                    # Now close the session
                    await session.close()

                    # If AI concluded, wait for the farewell audio to finish playing
                    if live_concluded or interview_ending:
                        logger.info("⏳ Waiting for conclusion audio to finish playing...")
                        await asyncio.sleep(5)

                    # Generate assessment for any interview with conversation history
                    history = conversation.get_history_for_llm() if conversation else []
                    if len(history) >= 2:
                        # Mark interview as completed and save transcript IMMEDIATELY
                        _fin_config = session_configs.get(conversation_id, {})
                        _app_id_fin = _fin_config.get("application_id")
                        _iv_id_fin = _fin_config.get("interview_id")
                        _iv_fin = None
                        try:
                            # Look up by interview_id first (most reliable), then application_id
                            if _iv_id_fin:
                                _iv_fin = db_ws.query(DBInterview).filter(
                                    DBInterview.interview_id == _iv_id_fin
                                ).first()
                            if not _iv_fin and _app_id_fin:
                                _iv_fin = db_ws.query(DBInterview).filter(
                                    DBInterview.application_id == _app_id_fin
                                ).order_by(DBInterview.created_at.desc()).first()

                            if _iv_fin:
                                if _iv_fin.status != "completed":
                                    _iv_fin.status = "completed"
                                    _iv_fin.completed_at = datetime.now()
                                # Also update the application
                                if _iv_fin.application_id:
                                    _app_fin = db_ws.query(DBApplication).filter(
                                        DBApplication.application_id == _iv_fin.application_id
                                    ).first()
                                    if _app_fin:
                                        _app_fin.interview_completed_at = datetime.now()
                                        _app_fin.updated_at = datetime.now()
                                # Upload per-turn audio files and update history with audio_key
                                if per_turn_audio_data:
                                    import struct, io
                                    for turn_idx, turn_pcm in per_turn_audio_data:
                                        try:
                                            sr = 16000
                                            wav_buf = io.BytesIO()
                                            wav_buf.write(b"RIFF")
                                            wav_buf.write(struct.pack('<I', 36 + len(turn_pcm)))
                                            wav_buf.write(b"WAVE")
                                            wav_buf.write(b"fmt ")
                                            wav_buf.write(struct.pack('<IHHIIHH', 16, 1, 1, sr, sr * 2, 2, 16))
                                            wav_buf.write(b"data")
                                            wav_buf.write(struct.pack('<I', len(turn_pcm)))
                                            wav_buf.write(turn_pcm)
                                            turn_key = f"recordings/{_iv_fin.interview_id}_turn{turn_idx}.wav"
                                            s3_upload(wav_buf.getvalue(), turn_key, content_type="audio/wav", local_dir=UPLOADS_DIR)
                                            # Update the matching message in history with audio_key
                                            for msg in history:
                                                if msg.get("audio_turn") == turn_idx:
                                                    msg["audio_key"] = turn_key
                                                    del msg["audio_turn"]
                                                    break
                                            logger.info(f"🔊 Saved per-turn audio turn {turn_idx} ({len(turn_pcm)} bytes) → {turn_key}")
                                        except Exception as e:
                                            logger.error(f"Failed to save per-turn audio turn {turn_idx}: {e}")
                                    # Clean up any remaining audio_turn markers
                                    for msg in history:
                                        msg.pop("audio_turn", None)
                                # Save transcript immediately so admin can see it
                                _iv_fin.conversation_history = json.dumps(history)
                                # Save full interview recording (both AI + candidate audio) as WAV to S3
                                logger.info(f"📊 Audio: {len(recording_timeline)} timeline chunks, {len(per_turn_audio_data)} per-turn segments")
                                if recording_timeline:
                                    try:
                                        import base64, struct, io, array

                                        def _resample_24k_to_16k(pcm_24k_bytes: bytes) -> bytes:
                                            """Resample 24kHz PCM to 16kHz using linear interpolation (ratio 2:3)."""
                                            n_samples_in = len(pcm_24k_bytes) // 2
                                            if n_samples_in < 2:
                                                return b""
                                            samples_in = struct.unpack(f'<{n_samples_in}h', pcm_24k_bytes[:n_samples_in * 2])
                                            # Output sample count: n_in * 16000/24000 = n_in * 2/3
                                            n_samples_out = int(n_samples_in * 2 / 3)
                                            if n_samples_out < 1:
                                                return b""
                                            out = array.array('h')
                                            for i in range(n_samples_out):
                                                # Map output index to input index (fractional)
                                                src = i * 1.5  # 24000/16000 = 1.5
                                                idx = int(src)
                                                frac = src - idx
                                                if idx + 1 < n_samples_in:
                                                    val = samples_in[idx] * (1.0 - frac) + samples_in[idx + 1] * frac
                                                else:
                                                    val = samples_in[min(idx, n_samples_in - 1)]
                                                out.append(max(-32768, min(32767, int(val))))
                                            return out.tobytes()

                                        # Build combined PCM at 16kHz from timeline
                                        combined_parts = []
                                        for source, chunk_b64 in recording_timeline:
                                            try:
                                                raw = base64.b64decode(chunk_b64)
                                                if source == "output":
                                                    # AI audio is 24kHz — resample to 16kHz
                                                    raw = _resample_24k_to_16k(raw)
                                                if raw:
                                                    combined_parts.append(raw)
                                            except Exception:
                                                pass
                                        if combined_parts:
                                            pcm_data = b"".join(combined_parts)
                                            # Build WAV header (16kHz, 16-bit, mono)
                                            sr = 16000
                                            wav_buf = io.BytesIO()
                                            wav_buf.write(b"RIFF")
                                            wav_buf.write(struct.pack('<I', 36 + len(pcm_data)))
                                            wav_buf.write(b"WAVE")
                                            wav_buf.write(b"fmt ")
                                            wav_buf.write(struct.pack('<IHHIIHH', 16, 1, 1, sr, sr * 2, 2, 16))
                                            wav_buf.write(b"data")
                                            wav_buf.write(struct.pack('<I', len(pcm_data)))
                                            wav_buf.write(pcm_data)
                                            wav_bytes = wav_buf.getvalue()
                                            audio_key = f"recordings/{_iv_fin.interview_id}.wav"
                                            s3_upload(wav_bytes, audio_key, content_type="audio/wav", local_dir=UPLOADS_DIR)
                                            _iv_fin.recording_audio = audio_key
                                            logger.info(f"💾 Saved full interview recording ({len(pcm_data)} bytes PCM → WAV) to {audio_key}")
                                    except Exception as e:
                                        logger.error(f"Failed to save audio recording: {e}")
                                db_ws.commit()
                                logger.info(f"✅ Live interview {_iv_fin.interview_id} marked completed with transcript ({len(history)} messages)")
                            else:
                                logger.warning(f"⚠️ Could not find interview record to mark completed (interview_id={_iv_id_fin}, application_id={_app_id_fin})")
                        except Exception as e:
                            logger.error(f"Failed to mark interview completed: {e}")

                        # Send immediate placeholder to frontend
                        try:
                            await websocket.send_json({
                                "type": "assessment",
                                "assessment": "**Interview Completed**\n\nThank you for your time! Our HR team will review your application and get back to you soon.\n\nWe appreciate your interest in this position."
                            })
                        except Exception:
                            pass

                        # Log tested languages before assessment
                        if _req_langs_list and len(_req_langs_list) > 1:
                            tested = conversation.get_tested_languages()
                            untested = [l for l in _req_langs_list if l not in tested]
                            logger.info(f"🌐 Assessment: Tested languages: {list(tested)}, Untested: {untested}")

                        # Run assessment + DB write in background
                        _history_f = list(history)
                        _ctx_f = dict(conversation.get_interview_context()) if conversation.get_interview_context() else {}
                        _config_f = dict(session_configs.get(conversation_id, {}))
                        _candidate_name_f = conversation.get_candidate_name() or _config_f.get("candidate_name")
                        _feedback_language_f = interview_start_language or None

                        def _run_live_final_assessment_bg():
                            try:
                                from backend.database import SessionLocal
                                db_bg = SessionLocal()
                                try:
                                    from backend.services.openai_llm import generate_assessment as gen_assess
                                    assessment = gen_assess(_history_f, interview_context=_ctx_f)
                                    recommendation = extract_recommendation(assessment)
                                    detailed_scores = extract_detailed_scores(assessment)

                                    application_id = _config_f.get("application_id")
                                    if not application_id:
                                        evaluation_id = _config_f.get("evaluation_id")
                                        if evaluation_id:
                                            if evaluation_id in cv_evaluations:
                                                application_id = cv_evaluations[evaluation_id].get("application_id")
                                            if not application_id:
                                                cv_eval = db_bg.query(DBCVEvaluation).filter(
                                                    DBCVEvaluation.evaluation_id == evaluation_id
                                                ).first()
                                                if cv_eval:
                                                    application_id = cv_eval.application_id

                                    job_offer_id = _config_f.get("job_offer_id")
                                    cv_text = _config_f.get("candidate_cv_text", "")

                                    interview_rec = None
                                    _bg_iv_id = _config_f.get("interview_id")
                                    if _bg_iv_id:
                                        interview_rec = db_bg.query(DBInterview).filter(
                                            DBInterview.interview_id == _bg_iv_id
                                        ).first()
                                    if not interview_rec and application_id:
                                        interview_rec = db_bg.query(DBInterview).filter(
                                            DBInterview.application_id == application_id
                                        ).order_by(DBInterview.created_at.desc()).first()

                                    if not interview_rec:
                                        interview_rec = DBInterview(
                                            application_id=application_id,
                                            job_offer_id=job_offer_id or "",
                                            candidate_name=_candidate_name_f,
                                            cv_text=cv_text[:5000] if cv_text else None,
                                            status="completed",
                                            assessment=assessment,
                                            recommendation=recommendation,
                                            evaluation_scores=json.dumps(detailed_scores),
                                            conversation_history=json.dumps(_history_f),
                                            completed_at=datetime.now()
                                        )
                                        db_bg.add(interview_rec)
                                    else:
                                        interview_rec.status = "completed"
                                        interview_rec.assessment = assessment
                                        interview_rec.recommendation = recommendation
                                        interview_rec.evaluation_scores = json.dumps(detailed_scores)
                                        interview_rec.conversation_history = json.dumps(_history_f)
                                        interview_rec.completed_at = datetime.now()

                                    if application_id:
                                        app = db_bg.query(DBApplication).filter(
                                            DBApplication.application_id == application_id
                                        ).first()
                                        if app:
                                            app.interview_completed_at = datetime.now()
                                            app.interview_assessment = assessment
                                            app.interview_recommendation = recommendation
                                            app.updated_at = datetime.now()

                                    db_bg.commit()
                                    logger.info(f"✅ [BG] OpenAI Realtime assessment stored: {interview_rec.interview_id}")

                                    # Generate transcript annotations
                                    try:
                                        from backend.services.language_llm_openai import generate_transcript_annotations as gem_ann
                                        annotations = gem_ann(conversation_history=_history_f, feedback_language=_feedback_language_f)
                                        for i, msg in enumerate(_history_f):
                                            if msg["role"] == "user":
                                                idx_str = str(i)
                                                if idx_str in annotations:
                                                    msg["ai_comment"] = annotations[idx_str]
                                        interview_rec.conversation_history = json.dumps(_history_f)
                                        db_bg.commit()
                                        logger.info(f"✅ [BG] Live transcript annotations saved: {interview_rec.interview_id}")
                                    except Exception as e:
                                        logger.error(f"❌ [BG] Live transcript annotations failed: {e}")

                                except Exception as e:
                                    logger.error(f"❌ [BG] OpenAI Realtime assessment error: {e}")
                                    db_bg.rollback()
                                    # Save error info so admin can see it and regenerate later
                                    try:
                                        _iv_err = None
                                        _bg_iv_id_err = _config_f.get("interview_id")
                                        if _bg_iv_id_err:
                                            _iv_err = db_bg.query(DBInterview).filter(
                                                DBInterview.interview_id == _bg_iv_id_err
                                            ).first()
                                        if _iv_err and not _iv_err.assessment:
                                            error_msg = str(e)
                                            if "quota" in error_msg.lower() or "429" in error_msg or "resource" in error_msg.lower():
                                                _iv_err.assessment = "[ASSESSMENT_FAILED:QUOTA] API quota exceeded. Please reload credits and regenerate the assessment."
                                            else:
                                                _iv_err.assessment = f"[ASSESSMENT_FAILED] Assessment generation failed: {error_msg[:200]}. You can regenerate it from the admin panel."
                                            db_bg.commit()
                                            logger.info(f"💾 Saved assessment error marker for interview {_bg_iv_id_err}")
                                    except Exception as save_err:
                                        logger.error(f"Failed to save assessment error marker: {save_err}")
                                finally:
                                    db_bg.close()
                            except Exception as e:
                                logger.error(f"❌ [BG] OpenAI Realtime assessment thread error: {e}")

                        import threading
                        threading.Thread(target=_run_live_final_assessment_bg, daemon=True).start()
                    else:
                        # Not enough history — still send a completion message
                        try:
                            await websocket.send_json({
                                "type": "assessment",
                                "assessment": "**Interview Ended**\n\nThank you for your time. The interview was too short to generate a full assessment."
                            })
                        except Exception:
                            pass

                    # Close WebSocket so frontend knows the interview is over
                    logger.info("🔌 Closing WebSocket after OpenAI Realtime session ended")
                    try:
                        await websocket.close(code=1000, reason="Interview concluded")
                    except Exception:
                        pass

                return  # Exit WebSocket handler after live mode

            # ============================================================
            # CLASSIC MODE — separate STT + LLM + TTS pipeline
            # ============================================================

            # Start with pre-check phase: audio check
            logger.info("🎯 Starting pre-check phase: audio check...")
            llm_funcs = get_llm_functions(config["llm_provider"])
            interview_start_language = conversation.interview_start_language if conversation.interview_start_language else None
            audio_check_text = llm_funcs["generate_audio_check"](model_id=config["llm_model"], language=interview_start_language)
            logger.info(f"💬 Audio check: {audio_check_text}")
            conversation.add_message("interviewer", audio_check_text)
            
            # Convert to speech using selected TTS provider
            tts_func = get_tts_function(config["tts_provider"])
            voice_id = get_voice_id(config["tts_provider"])
            
            try:
                audio_bytes = tts_func(audio_check_text, voice_id, config["tts_model"])
                audio_format = "mp3"
            except ValueError as e:
                # Quota exceeded or other user-friendly error
                error_msg = str(e)
                logger.error(f"❌ TTS Error: {error_msg}")
                await websocket.send_json({
                    "type": "error",
                    "message": error_msg
                })
                return
            except Exception as e:
                error_msg = f"TTS service error: {str(e)}"
                logger.error(f"❌ TTS Error: {error_msg}")
                await websocket.send_json({
                    "type": "error",
                    "message": "Text-to-speech service error. Please try again or switch to a different TTS provider."
                })
                return
            
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            await websocket.send_json({
                "type": "greeting",
                "conversation_id": conversation_id,
                "text": audio_check_text,
                "audio": audio_base64,
                "audio_format": audio_format,
                "phase": conversation.get_current_phase(),
                "time_limit_minutes": interview_duration_minutes
            })
        
        # Handle messages
        while True:
            message = await websocket.receive()
            
            # Check time limit before processing any message
            if conversation_id:
                should_continue = await check_and_handle_time_limit(
                    conversation_id, websocket, active_conversations, 
                    session_configs, interview_start_times
                )
                if not should_continue:
                    break  # Interview ended due to time limit
            
            if "text" in message:
                data = json.loads(message["text"])
                
                # Handle end interview request
                if data.get("type") == "end_interview":
                    conv_id = data.get("conversation_id")
                    if conv_id and conv_id in active_conversations:
                        conv = active_conversations[conv_id]
                        history = conv.get_history_for_llm()
                        interview_context = conv.get_interview_context()
                        config = session_configs.get(conv_id, {})

                        current_phase = conv.get_current_phase()
                        is_interview_phase = current_phase == ConversationManager.PHASE_INTERVIEW

                        # Send immediate response — candidate doesn't wait for assessment
                        if is_interview_phase and len(history) >= 2:
                            # Mark interview as completed IMMEDIATELY to prevent restart
                            _app_id = config.get("application_id")
                            if _app_id:
                                _iv = db_ws.query(DBInterview).filter(
                                    DBInterview.application_id == _app_id
                                ).order_by(DBInterview.created_at.desc()).first()
                                if _iv and _iv.status == "pending":
                                    _iv.status = "completed"
                                    _iv.completed_at = datetime.now()
                                    db_ws.commit()
                                    logger.info(f"✅ Interview {_iv.interview_id} marked completed immediately")

                            await websocket.send_json({
                                "type": "assessment",
                                "assessment": "**Interview Completed**\n\nThank you for your time! Our HR team will review your application and get back to you soon.\n\nWe appreciate your interest in this position."
                            })

                            # Run assessment + annotations in background thread
                            _history = list(history)
                            _ctx = dict(interview_context) if interview_context else {}
                            _config = dict(config)
                            _conv_id = conv_id
                            _candidate_name = conv.get_candidate_name() or config.get("candidate_name")
                            _classic_feedback_lang = conv.interview_start_language or None

                            def _run_classic_assessment_bg():
                                try:
                                    from backend.database import SessionLocal
                                    db_bg = SessionLocal()
                                    try:
                                        llm_prov = _config.get("llm_provider", DEFAULT_LLM_PROVIDER)
                                        llm_mod = _config.get("llm_model", LLM_PROVIDERS[llm_prov]["default_model"])
                                        llm_funcs_bg = get_llm_functions(llm_prov)

                                        assessment = llm_funcs_bg["generate_assessment"](
                                            _history, model_id=llm_mod, interview_context=_ctx
                                        )
                                        recommendation = extract_recommendation(assessment)
                                        detailed_scores = extract_detailed_scores(assessment)

                                        application_id = _config.get("application_id")
                                        if not application_id:
                                            evaluation_id = _config.get("evaluation_id")
                                            if evaluation_id:
                                                if evaluation_id in cv_evaluations:
                                                    application_id = cv_evaluations[evaluation_id].get("application_id")
                                                if not application_id:
                                                    cv_eval = db_bg.query(DBCVEvaluation).filter(
                                                        DBCVEvaluation.evaluation_id == evaluation_id
                                                    ).first()
                                                    if cv_eval:
                                                        application_id = cv_eval.application_id

                                        job_offer_id = _config.get("job_offer_id")
                                        cv_text = _config.get("candidate_cv_text", "")

                                        interview_rec = None
                                        if application_id:
                                            interview_rec = db_bg.query(DBInterview).filter(
                                                DBInterview.application_id == application_id
                                            ).order_by(DBInterview.created_at.desc()).first()

                                        if not interview_rec:
                                            interview_rec = DBInterview(
                                                application_id=application_id,
                                                job_offer_id=job_offer_id or "",
                                                candidate_name=_candidate_name,
                                                cv_text=cv_text[:5000] if cv_text else None,
                                                status="completed",
                                                assessment=assessment,
                                                recommendation=recommendation,
                                                evaluation_scores=json.dumps(detailed_scores),
                                                conversation_history=json.dumps(_history),
                                                completed_at=datetime.now()
                                            )
                                            db_bg.add(interview_rec)
                                        else:
                                            interview_rec.status = "completed"
                                            interview_rec.assessment = assessment
                                            interview_rec.recommendation = recommendation
                                            interview_rec.evaluation_scores = json.dumps(detailed_scores)
                                            interview_rec.conversation_history = json.dumps(_history)
                                            interview_rec.completed_at = datetime.now()

                                        if application_id:
                                            app = db_bg.query(DBApplication).filter(
                                                DBApplication.application_id == application_id
                                            ).first()
                                            if app:
                                                app.interview_completed_at = datetime.now()
                                                app.interview_assessment = assessment
                                                app.interview_recommendation = recommendation
                                                app.updated_at = datetime.now()

                                        db_bg.commit()
                                        logger.info(f"✅ [BG] Classic interview assessment stored: {interview_rec.interview_id}")

                                        # Generate transcript annotations
                                        try:
                                            if llm_prov == "gpt" or llm_prov == "openai":
                                                from backend.services.language_llm_openai import generate_transcript_annotations
                                                annotations = generate_transcript_annotations(conversation_history=_history, model_id=llm_mod, feedback_language=_classic_feedback_lang)
                                            else:
                                                from backend.services.language_llm_openai import generate_transcript_annotations as gem_ann
                                                annotations = gem_ann(conversation_history=_history, model_id=llm_mod, feedback_language=_classic_feedback_lang)

                                            for i, msg in enumerate(_history):
                                                if msg["role"] == "user":
                                                    idx_str = str(i)
                                                    if idx_str in annotations:
                                                        msg["ai_comment"] = annotations[idx_str]

                                            interview_rec.conversation_history = json.dumps(_history)
                                            db_bg.commit()
                                            logger.info(f"✅ [BG] Transcript annotations saved: {interview_rec.interview_id}")
                                        except Exception as e:
                                            logger.error(f"❌ [BG] Transcript annotations failed: {e}")

                                    except Exception as e:
                                        logger.error(f"❌ [BG] Classic assessment error: {e}")
                                        db_bg.rollback()
                                        try:
                                            if interview_rec and not interview_rec.assessment:
                                                error_msg = str(e)
                                                if "quota" in error_msg.lower() or "429" in error_msg or "resource" in error_msg.lower():
                                                    interview_rec.assessment = "[ASSESSMENT_FAILED:QUOTA] API quota exceeded. Please reload credits and regenerate the assessment."
                                                else:
                                                    interview_rec.assessment = f"[ASSESSMENT_FAILED] Assessment generation failed: {error_msg[:200]}. You can regenerate it from the admin panel."
                                                db_bg.commit()
                                        except Exception:
                                            pass
                                    finally:
                                        db_bg.close()
                                except Exception as e:
                                    logger.error(f"❌ [BG] Classic assessment thread error: {e}")

                            import threading
                            threading.Thread(target=_run_classic_assessment_bg, daemon=True).start()
                        elif not is_interview_phase:
                            logger.warning(f"⚠️ Interview ended during {current_phase} phase - no assessment generated")
                            await websocket.send_json({
                                "type": "assessment",
                                "assessment": "**Interview Ended**\n\nThank you for your time! Our HR team will review your application and get back to you soon."
                            })
                        else:
                            logger.warning(f"⚠️ Insufficient conversation history for assessment")
                            await websocket.send_json({
                                "type": "assessment",
                                "assessment": "**Interview Ended**\n\nThank you for your time! Our HR team will review your application and get back to you soon."
                            })
                        
                        # Clean up
                        if conv_id in active_conversations:
                            del active_conversations[conv_id]
                        if conv_id in session_configs:
                            del session_configs[conv_id]
                        if conv_id in interview_start_times:
                            del interview_start_times[conv_id]
                        cleanup_dedup_cache(conv_id)
                        
                        # Wait for any final audio before closing
                        logger.info("⏳ Waiting 5 seconds before closing connection...")
                        await asyncio.sleep(5)
                        
                        # Close WebSocket connection
                        logger.info(f"🔌 Closing WebSocket connection after manual end")
                        await websocket.close(code=1000, reason="Interview ended by user")
                    break
                
                # Handle streaming audio start
                elif data.get("type") == "audio_stream_start":
                    conversation_id = data.get("conversation_id")
                    if conversation_id not in active_conversations:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Conversation not found"
                        })
                        continue
                    
                    config = session_configs.get(conversation_id, {})
                    
                    # Create streaming STT session
                    if is_streaming_stt_provider(config.get("stt_provider")):
                        # Determine STT language from conversation/job offer
                        conv = active_conversations.get(conversation_id)
                        stt_lang = "en"
                        if conv and conv.interview_start_language:
                            stt_lang = get_language_code(conv.interview_start_language) or "en"
                        logger.info(f"🎤 Starting streaming STT session for {conversation_id} (language={stt_lang})")

                        stt_session = ElevenLabsSTTStreaming(
                            model_id="scribe_v2_realtime",
                            language=stt_lang,
                        )
                        
                        if await stt_session.connect():
                            streaming_stt_sessions[conversation_id] = {
                                "session": stt_session,
                                "start_time": time.time(),
                            }
                            await websocket.send_json({
                                "type": "stream_ready",
                                "conversation_id": conversation_id
                            })
                        else:
                            await websocket.send_json({
                                "type": "error",
                                "message": "Failed to start streaming session"
                            })
                
                # Handle streaming audio chunk
                elif data.get("type") == "audio_chunk":
                    conversation_id = data.get("conversation_id")
                    audio_data = data.get("audio")
                    audio_format = data.get("format", "webm")

                    if conversation_id in streaming_stt_sessions:
                        try:
                            audio_bytes = base64.b64decode(audio_data)
                            stt_session = streaming_stt_sessions[conversation_id]["session"]
                            await stt_session.send_audio_chunk(audio_bytes, audio_format=audio_format)
                        except ValueError as e:
                            # Conversion failed - send error to client
                            logger.error(f"❌ Audio conversion failed: {e}")
                            await websocket.send_json({
                                "type": "error",
                                "message": "Audio conversion failed. Please install ffmpeg to use streaming STT."
                            })
                            # Clean up session
                            if conversation_id in streaming_stt_sessions:
                                await streaming_stt_sessions[conversation_id]["session"].close()
                                del streaming_stt_sessions[conversation_id]
                
                # Handle streaming audio commit (end of speech)
                elif data.get("type") == "audio_commit":
                    conversation_id = data.get("conversation_id")
                    
                    if conversation_id not in active_conversations:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Conversation not found"
                        })
                        continue
                    
                    conversation = active_conversations[conversation_id]
                    config = session_configs.get(conversation_id, {})
                    
                    if conversation_id in streaming_stt_sessions:
                        # Get streaming STT result
                        stt_info = streaming_stt_sessions[conversation_id]
                        stt_session = stt_info["session"]
                        stt_start_time = stt_info["start_time"]
                        
                        logger.info(f"🎤 Committing streaming audio for {conversation_id}")
                        await stt_session.commit()

                        # Wait for transcript using event-driven approach (no polling)
                        user_text = await stt_session.wait_for_transcript(timeout=5.0)

                        if not user_text.strip():
                            logger.warning(f"⚠️ No transcript received - checking for partial transcripts")
                        
                        stt_duration = time.time() - stt_start_time
                        logger.info(f"⏱️ Streaming STT took {stt_duration:.2f}s (including speech time)")
                        
                        # Close session
                        await stt_session.close()
                        del streaming_stt_sessions[conversation_id]
                        
                        if not user_text.strip():
                            logger.warning(f"⚠️ No transcript received after timeout")
                            await websocket.send_json({
                                "type": "error",
                                "message": "No speech detected or transcript timeout"
                            })
                            continue
                        
                        logger.info(f"📝 User said: {user_text}")
                        total_start = time.time()
                        
                        conversation.add_message("user", user_text)
                        
                        # Check if we're in pre-check phase
                        llm_funcs = get_llm_functions(config.get("llm_provider", DEFAULT_LLM_PROVIDER))
                        should_continue = await handle_precheck_response(
                            conversation, user_text, config, llm_funcs, websocket, conversation_id
                        )
                        
                        if not should_continue:
                            continue  # Pre-check handled, wait for next message
                        
                        # Normal interview response
                        history = conversation.get_history_for_llm()
                        llm_provider = config.get("llm_provider", DEFAULT_LLM_PROVIDER)
                        llm_model = config.get("llm_model", LLM_PROVIDERS[llm_provider]["default_model"])
                        
                        # Calculate time remaining using config duration
                        time_remaining_minutes = None
                        interview_time_limit = config.get("interview_duration_minutes", INTERVIEW_TIME_LIMIT_MINUTES)
                        if conversation_id in interview_start_times:
                            elapsed_minutes = (time.time() - interview_start_times[conversation_id]) / 60
                            time_remaining_minutes = max(0, interview_time_limit - elapsed_minutes)
                        
                        # Get interview context for contextual responses
                        interview_context = conversation.get_interview_context(time_remaining_minutes=time_remaining_minutes, total_interview_minutes=interview_time_limit)
                        
                        llm_start = time.time()
                        interviewer_response = llm_funcs["generate_response"](
                            history[:-1], 
                            user_text, 
                            model_id=llm_model,
                            interview_context=interview_context
                        )
                        llm_duration = time.time() - llm_start
                        logger.info(f"⏱️ LLM took {llm_duration:.2f}s")
                        
                        # Detect proactive language switch in AI response
                        response_lower = interviewer_response.lower()
                        required_langs = conversation.get_required_languages_list()
                        current_lang = conversation.get_current_language()
                        tested_langs = conversation.get_tested_languages()
                        
                        # Check if AI is switching to an untested language
                        if required_langs and len(required_langs) > 1:
                            untested_langs = [lang for lang in required_langs if lang not in tested_langs]
                            for lang in untested_langs:
                                lang_keywords = {
                                    "French": ["français", "francais", "french", "en français", "continuons en français"],
                                    "English": ["english", "anglais", "in english", "let's continue in english"],
                                    "Arabic": ["arabic", "arabe", "en arabe", "بالعربية"],
                                    "Spanish": ["spanish", "espagnol", "español", "en español"],
                                    "German": ["german", "allemand", "deutsch", "auf deutsch"]
                                }
                                if lang in lang_keywords:
                                    for keyword in lang_keywords[lang]:
                                        if keyword in response_lower and lang != current_lang:
                                            # AI is proactively switching to this language
                                            conversation.set_current_language(lang)
                                            logger.info(f"🌐 AI proactively switched to {lang} for language testing")
                                            break
                        
                        conversation.add_message("interviewer", interviewer_response)
                        # Increment question count for current language
                        conversation.increment_question_count()
                        
                        # Detect if AI concluded the interview before stripping the token
                        response_lower = interviewer_response.lower()
                        is_conclusion = ("[interview_concluded]" in response_lower) or any(phrase in response_lower for phrase in CONCLUSION_PHRASES)
                        
                        # Strip the token so it doesn't get spoken or shown to candidate
                        if "[interview_concluded]" in response_lower:
                            import re
                            interviewer_response = re.sub(r'\[INTERVIEW_CONCLUDED\]', '', interviewer_response, flags=re.IGNORECASE).strip()
                        
                        # Text to Speech using selected provider
                        tts_func = get_tts_function(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                        voice_id = get_voice_id(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                        tts_model = config.get("tts_model")
                        
                        tts_start = time.time()
                        try:
                            if not interviewer_response.strip():
                                # Avoid throwing ValueError if AI only responded with conclusion token
                                response_audio_bytes = b""
                                audio_format = "mp3"
                            else:
                                response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                                audio_format = "mp3"
                            tts_duration = time.time() - tts_start
                            logger.info(f"⏱️ TTS took {tts_duration:.2f}s")
                        except ValueError as e:
                            # Quota exceeded or other user-friendly error
                            error_msg = str(e)
                            logger.error(f"❌ TTS Error: {error_msg}")
                            await websocket.send_json({
                                "type": "error",
                                "message": error_msg
                            })
                            continue
                        except Exception as e:
                            error_msg = f"TTS service error: {str(e)}"
                            logger.error(f"❌ TTS Error: {error_msg}")
                            await websocket.send_json({
                                "type": "error",
                                "message": f"Text-to-speech service error. Please try again or switch to a different TTS provider."
                            })
                            continue
                        
                        total_duration = time.time() - total_start
                        logger.info(f"⏱️ TOTAL post-speech processing: {total_duration:.2f}s (LLM: {llm_duration:.2f}s + TTS: {tts_duration:.2f}s)")
                        
                        # Send the response first
                        response_audio_base64 = base64.b64encode(response_audio_bytes).decode('utf-8')
                        await websocket.send_json({
                            "type": "response",
                            "user_text": user_text,
                            "interviewer_text": interviewer_response,
                            "audio": response_audio_base64,
                            "audio_format": audio_format
                        })
                        
                        # If AI concluded and we're in interview phase, auto-generate assessment
                        if is_conclusion and conversation.get_current_phase() == ConversationManager.PHASE_INTERVIEW:
                            logger.info("🎯 AI concluded the interview - auto-generating assessment")
                            
                            # Wait for the closing audio to finish playing (typical closing is 10-15 seconds)
                            logger.info("⏳ Waiting 12 seconds for closing audio to finish...")
                            await asyncio.sleep(12)
                            
                            # Generate assessment
                            history = conversation.get_history_for_llm()
                            interview_context_final = conversation.get_interview_context()
                            llm_funcs = get_llm_functions(config.get("llm_provider", DEFAULT_LLM_PROVIDER))
                            
                            try:
                                assessment = llm_funcs["generate_assessment"](
                                    history, 
                                    model_id=llm_model,
                                    interview_context=interview_context_final
                                )
                                
                                # Store assessment in database
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
                                    candidate_name = conversation.get_candidate_name() or config.get("candidate_name")
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
                                    logger.info(f"✅ Interview assessment stored: interview_id={interview.interview_id}, recommendation={recommendation}")
                                    
                                    # Generate transcript annotations (AI feedback)
                                    _ws_ann_lang = conversation.interview_start_language if conversation else None
                                    try:
                                        if config.get("llm_provider", DEFAULT_LLM_PROVIDER) == "gpt":
                                            from backend.services.language_llm_openai import generate_transcript_annotations
                                            annotations = generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_ws_ann_lang)
                                        else:
                                            from backend.services.language_llm_openai import generate_transcript_annotations
                                            annotations = generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_ws_ann_lang)
                                        
                                        # Update conversation history with annotations
                                        for i, msg in enumerate(history):
                                            if msg["role"] == "user":
                                                idx_str = str(i)
                                                if idx_str in annotations:
                                                    msg["ai_comment"] = annotations[idx_str]
                                        
                                        interview.conversation_history = json.dumps(history)
                                        db.commit()
                                        logger.info("✅ Saved real-time interview transcript annotations")
                                    except Exception as e:
                                        logger.error(f"❌ Error generating real-time transcript annotations: {e}")
                                    
                                except Exception as e:
                                    logger.error(f"❌ Error storing interview assessment: {e}")
                                    db.rollback() if 'db' in locals() else None
                                
                                # Send neutral completion message to candidate (no feedback)
                                await websocket.send_json({
                                    "type": "assessment",
                                    "assessment": "**Interview Completed**\n\nThank you for your time! Our HR team will review your application and get back to you soon.\n\nWe appreciate your interest in this position.",
                                    "interview_completed": True,
                                    "interview_id": interview.interview_id if 'interview' in locals() and interview else None
                                })
                                
                                # Clean up and close connection
                                if conversation_id in active_conversations:
                                    del active_conversations[conversation_id]
                                if conversation_id in session_configs:
                                    del session_configs[conversation_id]
                                if conversation_id in interview_start_times:
                                    del interview_start_times[conversation_id]
                                cleanup_dedup_cache(conversation_id)
                                
                                logger.info("✅ Interview auto-concluded by AI")
                                
                                # Wait additional time before closing to ensure audio finished
                                logger.info("⏳ Waiting 5 more seconds before closing connection...")
                                await asyncio.sleep(5)
                                
                                # Close WebSocket connection
                                logger.info(f"🔌 Closing WebSocket connection after AI conclusion")
                                await websocket.close(code=1000, reason="Interview concluded by AI")
                                break  # Exit message loop
                                
                            except Exception as e:
                                logger.error(f"❌ Error generating assessment: {e}")
                                # Continue normally if assessment generation fails
                
                # Handle audio message (batch mode - existing)
                elif data.get("type") == "audio":
                    conversation_id = data.get("conversation_id")
                    if conversation_id not in active_conversations:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Conversation not found"
                        })
                        continue
                    
                    conversation = active_conversations[conversation_id]
                    config = session_configs.get(conversation_id, {})
                    audio_data = data.get("audio")
                    
                    # Decode audio
                    audio_bytes = base64.b64decode(audio_data)
                    logger.info(f"🎧 Received audio: {len(audio_bytes)} bytes")
                    
                    # Check for duplicate audio message
                    if is_duplicate_message(conversation_id, audio_bytes):
                        logger.warning(f"⚠️ Skipping duplicate audio for {conversation_id}")
                        continue
                    
                    total_start = time.time()
                    
                    # Speech to Text using selected provider
                    stt_func = get_stt_function(config.get("stt_provider", DEFAULT_STT_PROVIDER))
                    stt_model = config.get("stt_model", STT_PROVIDERS[DEFAULT_STT_PROVIDER]["default_model"])
                    
                    logger.info(f"🎤 Processing with STT: {config.get('stt_provider')} / {stt_model}")
                    
                    stt_start = time.time()
                    try:
                        user_text = stt_func(audio_bytes, model_id=stt_model)
                    except Exception as e:
                        logger.warning(f"⚠️ STT failed to process chunk (likely too short): {e}")
                        await websocket.send_json({
                            "type": "error",
                            "message": "Audio chunk too short or unrecognized. Please speak again."
                        })
                        continue

                    stt_duration = time.time() - stt_start
                    logger.info(f"⏱️ STT took {stt_duration:.2f}s")
                    
                    logger.info(f"📝 User said: {user_text}")
                    if not user_text.strip():
                        await websocket.send_json({
                            "type": "error",
                            "message": "No speech detected"
                        })
                        continue
                    
                    conversation.add_message("user", user_text)
                    
                    # Check if we're in pre-check phase
                    llm_funcs = get_llm_functions(config.get("llm_provider", DEFAULT_LLM_PROVIDER))
                    should_continue = await handle_precheck_response(
                        conversation, user_text, config, llm_funcs, websocket, conversation_id
                    )
                    
                    if not should_continue:
                        continue  # Pre-check handled, wait for next message
                    
                    # Normal interview response
                    history = conversation.get_history_for_llm()
                    
                    # Calculate time remaining using config duration
                    time_remaining_minutes = None
                    interview_time_limit = config.get("interview_duration_minutes", INTERVIEW_TIME_LIMIT_MINUTES)
                    if conversation_id in interview_start_times:
                        elapsed_minutes = (time.time() - interview_start_times[conversation_id]) / 60
                        time_remaining_minutes = max(0, interview_time_limit - elapsed_minutes)
                    
                    interview_context = conversation.get_interview_context(time_remaining_minutes=time_remaining_minutes, total_interview_minutes=interview_time_limit)
                    llm_provider = config.get("llm_provider", DEFAULT_LLM_PROVIDER)
                    llm_model = config.get("llm_model", LLM_PROVIDERS[llm_provider]["default_model"])
                    
                    # Detect language switch requests from candidate
                    language_switch_keywords = [
                        "switch to", "switch language", "speak in", "parler en", "parlez", "continue in",
                        "now in", "in english", "in french", "en français", "en anglais", "en arabe",
                        "can we speak", "peut-on parler", "let's speak", "parlons", "change to",
                        "change language", "changer de langue", "autre langue"
                    ]
                    user_lower = user_text.lower()
                    is_language_switch = any(keyword in user_lower for keyword in language_switch_keywords)
                    
                    # Detect target language
                    target_language = None
                    if is_language_switch:
                        if "french" in user_lower or "français" in user_lower or "francais" in user_lower:
                            target_language = "French"
                        elif "english" in user_lower or "anglais" in user_lower:
                            target_language = "English"
                        elif "arabic" in user_lower or "arabe" in user_lower:
                            target_language = "Arabic"
                        elif "spanish" in user_lower or "espagnol" in user_lower:
                            target_language = "Spanish"
                        # If language switch detected but no specific language, check required languages
                        if not target_language:
                            required_langs = conversation.get_required_languages_list()
                            if required_langs:
                                # Switch to first untested language or next in list
                                tested = conversation.get_tested_languages()
                                untested = [lang for lang in required_langs if lang not in tested]
                                if untested:
                                    target_language = untested[0]
                    
                    if target_language:
                        conversation.set_current_language(target_language)
                        logger.info(f"🌐 Language switch detected: Switching to {target_language}")
                    
                    llm_start = time.time()
                    interviewer_response = llm_funcs["generate_response"](
                        history[:-1], 
                        user_text, 
                        model_id=llm_model,
                        interview_context=interview_context
                    )
                    llm_duration = time.time() - llm_start
                    logger.info(f"⏱️ LLM took {llm_duration:.2f}s")
                    
                    # Detect proactive language switch in AI response
                    response_lower = interviewer_response.lower()
                    required_langs = conversation.get_required_languages_list()
                    current_lang = conversation.get_current_language()
                    tested_langs = conversation.get_tested_languages()
                    
                    # Check if AI is switching to an untested language
                    if required_langs and len(required_langs) > 1:
                        untested_langs = [lang for lang in required_langs if lang not in tested_langs]
                        for lang in untested_langs:
                            lang_keywords = {
                                "French": ["français", "francais", "french", "en français", "continuons en français"],
                                "English": ["english", "anglais", "in english", "let's continue in english"],
                                "Arabic": ["arabic", "arabe", "en arabe", "بالعربية"],
                                "Spanish": ["spanish", "espagnol", "español", "en español"],
                                "German": ["german", "allemand", "deutsch", "auf deutsch"]
                            }
                            if lang in lang_keywords:
                                for keyword in lang_keywords[lang]:
                                    if keyword in response_lower and lang != current_lang:
                                        # AI is proactively switching to this language
                                        conversation.set_current_language(lang)
                                        logger.info(f"🌐 AI proactively switched to {lang} for language testing")
                                        break
                    
                    conversation.add_message("interviewer", interviewer_response)
                    # Increment question count for current language
                    conversation.increment_question_count()
                    
                    # Detect if AI concluded the interview before stripping the token
                    response_lower = interviewer_response.lower()
                    is_conclusion = ("[interview_concluded]" in response_lower) or any(phrase in response_lower for phrase in CONCLUSION_PHRASES)
                    
                    # Strip the token so it doesn't get spoken or shown to candidate
                    if "[interview_concluded]" in response_lower:
                        import re
                        interviewer_response = re.sub(r'\[INTERVIEW_CONCLUDED\]', '', interviewer_response, flags=re.IGNORECASE).strip()
                    
                    # Text to Speech using selected provider
                    tts_func = get_tts_function(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    voice_id = get_voice_id(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    tts_model = config.get("tts_model")
                    
                    tts_start = time.time()
                    try:
                        if not interviewer_response.strip():
                            # Avoid throwing ValueError if AI only responded with conclusion token
                            response_audio_bytes = b""
                            audio_format = "mp3"
                        else:
                            response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                            audio_format = "mp3"
                        tts_duration = time.time() - tts_start
                        logger.info(f"⏱️ TTS took {tts_duration:.2f}s")
                    except ValueError as e:
                        # Quota exceeded or other user-friendly error
                        error_msg = str(e)
                        logger.error(f"❌ TTS Error: {error_msg}")
                        await websocket.send_json({
                            "type": "error",
                            "message": error_msg
                        })
                        continue
                    except Exception as e:
                        error_msg = f"TTS service error: {str(e)}"
                        logger.error(f"❌ TTS Error: {error_msg}")
                        await websocket.send_json({
                            "type": "error",
                            "message": "Text-to-speech service error. Please try again or switch to a different TTS provider."
                        })
                        continue
                    
                    # Send the response first
                    response_audio_base64 = base64.b64encode(response_audio_bytes).decode('utf-8')
                    await websocket.send_json({
                        "type": "response",
                        "user_text": user_text,
                        "interviewer_text": interviewer_response,
                        "audio": response_audio_base64,
                        "audio_format": audio_format
                    })
                    
                    # If AI concluded and we're in interview phase, auto-generate assessment
                    if is_conclusion and conversation.get_current_phase() == ConversationManager.PHASE_INTERVIEW:
                        logger.info("🎯 AI concluded the interview - auto-generating assessment")
                        
                        # Wait for the closing audio to finish playing (typical closing is 10-15 seconds)
                        logger.info("⏳ Waiting 12 seconds for closing audio to finish...")
                        await asyncio.sleep(12)
                        
                        # Generate assessment
                        history = conversation.get_history_for_llm()
                        interview_context_final = conversation.get_interview_context()
                        llm_funcs = get_llm_functions(config.get("llm_provider", DEFAULT_LLM_PROVIDER))
                        
                        try:
                            assessment = llm_funcs["generate_assessment"](
                                history, 
                                model_id=llm_model,
                                interview_context=interview_context_final
                            )
                            
                            # Store assessment in database
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
                                candidate_name = conversation.get_candidate_name() or config.get("candidate_name")
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
                                logger.info(f"✅ Interview assessment stored: interview_id={interview.interview_id}, recommendation={recommendation}")
                                
                                # Generate transcript annotations (AI feedback)
                                _rt_ann_lang = conversation.interview_start_language if conversation else None
                                try:
                                    if config.get("llm_provider", DEFAULT_LLM_PROVIDER) == "gpt":
                                        from backend.services.language_llm_openai import generate_transcript_annotations
                                        annotations = generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_rt_ann_lang)
                                    else:
                                        from backend.services.language_llm_openai import generate_transcript_annotations
                                        annotations = generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_rt_ann_lang)
                                    
                                    # Update conversation history with annotations
                                    for i, msg in enumerate(history):
                                        if msg["role"] == "user":
                                            idx_str = str(i)
                                            if idx_str in annotations:
                                                msg["ai_comment"] = annotations[idx_str]
                                    
                                    interview.conversation_history = json.dumps(history)
                                    db.commit()
                                    logger.info("✅ Saved real-time interview transcript annotations")
                                except Exception as e:
                                    logger.error(f"❌ Error generating real-time transcript annotations: {e}")
                                
                            except Exception as e:
                                logger.error(f"❌ Error storing interview assessment: {e}")
                                db.rollback() if 'db' in locals() else None
                            
                            # Send neutral completion message to candidate (no feedback)
                            await websocket.send_json({
                                "type": "assessment",
                                "assessment": "**Interview Completed**\n\nThank you for your time! Our HR team will review your application and get back to you soon.\n\nWe appreciate your interest in this position.",
                                "interview_completed": True,
                                "interview_id": interview.interview_id if 'interview' in locals() and interview else None
                            })
                            
                            # Clean up and close connection
                            if conversation_id in active_conversations:
                                del active_conversations[conversation_id]
                            if conversation_id in session_configs:
                                del session_configs[conversation_id]
                            if conversation_id in interview_start_times:
                                del interview_start_times[conversation_id]
                            cleanup_dedup_cache(conversation_id)
                            
                            logger.info("✅ Interview auto-concluded by AI")
                            
                            # Wait additional time before closing to ensure audio finished
                            logger.info("⏳ Waiting 5 more seconds before closing connection...")
                            await asyncio.sleep(5)
                            
                            # Close WebSocket connection
                            logger.info(f"🔌 Closing WebSocket connection after AI conclusion")
                            await websocket.close(code=1000, reason="Interview concluded by AI")
                            break  # Exit message loop
                            
                        except Exception as e:
                            logger.error(f"❌ Error generating assessment: {e}")
                            # Continue normally if assessment generation fails
                    
                    # Track topics covered (simple keyword-based tracking)
                    # This is a basic implementation - the LLM should also be aware of topics
                    topic_keywords = {
                        "technical_skills": ["technical", "skill", "technology", "programming", "coding", "development"],
                        "experience": ["experience", "worked", "project", "previous", "past", "background"],
                        "education": ["education", "degree", "university", "school", "studied"],
                        "problem_solving": ["problem", "challenge", "solve", "solution", "approach"],
                        "communication": ["communicate", "explain", "present", "team", "collaborate"],
                        "motivation": ["motivation", "interested", "why", "passion", "excited"]
                    }
                    response_lower = interviewer_response.lower()
                    for topic, keywords in topic_keywords.items():
                        if any(keyword in response_lower for keyword in keywords):
                            conversation.add_covered_topic(topic)
                    
                    # Also check if LLM switched language in response
                    if any(phrase in interviewer_response.lower() for phrase in ["now let's continue in", "maintenant, continuons en", "let's switch to", "changeons de langue"]):
                        # Extract language from response if possible
                        for lang in ["French", "English", "Arabic", "Spanish"]:
                            if lang.lower() in interviewer_response.lower():
                                conversation.set_current_language(lang)
                                logger.info(f"🌐 LLM initiated language switch to: {lang}")
                                break
                    
                    # Note: Response was already sent above at line ~2935
                    # Total timing for this message processing
                    total_duration = time.time() - total_start
                    logger.info(f"⏱️ TOTAL processing time: {total_duration:.2f}s (STT: {stt_duration:.2f}s + LLM: {llm_duration:.2f}s + TTS: {tts_duration:.2f}s)")
            
            elif "bytes" in message:
                # Handle binary audio data
                if conversation_id and conversation:
                    audio_bytes = message["bytes"]
                    config = session_configs.get(conversation_id, {})
                    
                    # Speech to Text using selected provider
                    stt_func = get_stt_function(config.get("stt_provider", DEFAULT_STT_PROVIDER))
                    stt_model = config.get("stt_model", STT_PROVIDERS[DEFAULT_STT_PROVIDER]["default_model"])
                    
                    try:
                        user_text = stt_func(audio_bytes, model_id=stt_model)
                    except Exception as e:
                        logger.warning(f"⚠️ STT failed to process chunk (likely too short): {e}")
                        await websocket.send_json({
                            "type": "error",
                            "message": "Audio chunk too short or unrecognized. Please speak again."
                        })
                        continue
                    
                    if not user_text.strip():
                        await websocket.send_json({
                            "type": "error",
                            "message": "No speech detected"
                        })
                        continue
                    
                    conversation.add_message("user", user_text)
                    
                    # Check if we're in pre-check phase
                    llm_funcs = get_llm_functions(config.get("llm_provider", DEFAULT_LLM_PROVIDER))
                    should_continue = await handle_precheck_response(
                        conversation, user_text, config, llm_funcs, websocket, conversation_id
                    )
                    
                    if not should_continue:
                        continue  # Pre-check handled, wait for next message
                    
                    # Normal interview response
                    history = conversation.get_history_for_llm()
                    
                    # Calculate time remaining using config duration
                    time_remaining_minutes = None
                    interview_time_limit = config.get("interview_duration_minutes", INTERVIEW_TIME_LIMIT_MINUTES)
                    if conversation_id in interview_start_times:
                        elapsed_minutes = (time.time() - interview_start_times[conversation_id]) / 60
                        time_remaining_minutes = max(0, interview_time_limit - elapsed_minutes)
                    
                    interview_context = conversation.get_interview_context(time_remaining_minutes=time_remaining_minutes, total_interview_minutes=interview_time_limit)
                    llm_provider = config.get("llm_provider", DEFAULT_LLM_PROVIDER)
                    llm_model = config.get("llm_model", LLM_PROVIDERS[llm_provider]["default_model"])
                    interviewer_response = llm_funcs["generate_response"](
                        history[:-1], 
                        user_text, 
                        model_id=llm_model,
                        interview_context=interview_context
                    )
                    
                    # Detect proactive language switch in AI response
                    response_lower = interviewer_response.lower()
                    required_langs = conversation.get_required_languages_list()
                    current_lang = conversation.get_current_language()
                    tested_langs = conversation.get_tested_languages()
                    
                    # Check if AI is switching to an untested language
                    if required_langs and len(required_langs) > 1:
                        untested_langs = [lang for lang in required_langs if lang not in tested_langs]
                        for lang in untested_langs:
                            lang_keywords = {
                                "French": ["français", "francais", "french", "en français", "continuons en français"],
                                "English": ["english", "anglais", "in english", "let's continue in english"],
                                "Arabic": ["arabic", "arabe", "en arabe", "بالعربية"],
                                "Spanish": ["spanish", "espagnol", "español", "en español"],
                                "German": ["german", "allemand", "deutsch", "auf deutsch"]
                            }
                            if lang in lang_keywords:
                                for keyword in lang_keywords[lang]:
                                    if keyword in response_lower and lang != current_lang:
                                        # AI is proactively switching to this language
                                        conversation.set_current_language(lang)
                                        logger.info(f"🌐 AI proactively switched to {lang} for language testing")
                                        break
                    
                    conversation.add_message("interviewer", interviewer_response)
                    # Increment question count for current language
                    conversation.increment_question_count()
                    
                    # Detect if AI concluded the interview before stripping the token
                    response_lower = interviewer_response.lower()
                    is_conclusion = ("[interview_concluded]" in response_lower) or any(phrase in response_lower for phrase in CONCLUSION_PHRASES)
                    
                    # Strip the token so it doesn't get spoken or shown to candidate
                    if "[interview_concluded]" in response_lower:
                        import re
                        interviewer_response = re.sub(r'\[INTERVIEW_CONCLUDED\]', '', interviewer_response, flags=re.IGNORECASE).strip()
                    
                    # Text to Speech using selected provider
                    tts_func = get_tts_function(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    voice_id = get_voice_id(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    tts_model = config.get("tts_model")
                    
                    try:
                        if not interviewer_response.strip():
                            # Avoid throwing ValueError if AI only responded with conclusion token
                            response_audio_bytes = b""
                            audio_format = "mp3"
                        else:
                            response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                            audio_format = "mp3"
                    except ValueError as e:
                        # Quota exceeded or other user-friendly error
                        error_msg = str(e)
                        logger.error(f"❌ TTS Error: {error_msg}")
                        await websocket.send_json({
                            "type": "error",
                            "message": error_msg
                        })
                        continue
                    except Exception as e:
                        error_msg = f"TTS service error: {str(e)}"
                        logger.error(f"❌ TTS Error: {error_msg}")
                        await websocket.send_json({
                            "type": "error",
                            "message": "Text-to-speech service error. Please try again or switch to a different TTS provider."
                        })
                        continue
                    
                    # Send the response first
                    response_audio_base64 = base64.b64encode(response_audio_bytes).decode('utf-8')
                    await websocket.send_json({
                        "type": "response",
                        "user_text": user_text,
                        "interviewer_text": interviewer_response,
                        "audio": response_audio_base64,
                        "audio_format": audio_format
                    })
                    
                    # If AI concluded and we're in interview phase, auto-generate assessment
                    if is_conclusion and conversation.get_current_phase() == ConversationManager.PHASE_INTERVIEW:
                        logger.info("🎯 AI concluded the interview - auto-generating assessment")
                        
                        # Wait for the closing audio to finish playing (typical closing is 10-15 seconds)
                        logger.info("⏳ Waiting 12 seconds for closing audio to finish...")
                        await asyncio.sleep(12)
                        
                        # Generate assessment
                        history = conversation.get_history_for_llm()
                        interview_context_final = conversation.get_interview_context()
                        llm_funcs = get_llm_functions(config.get("llm_provider", DEFAULT_LLM_PROVIDER))
                        
                        try:
                            assessment = llm_funcs["generate_assessment"](
                                history, 
                                model_id=llm_model,
                                interview_context=interview_context_final
                            )
                            
                            # Store assessment in database
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
                                candidate_name = conversation.get_candidate_name() or config.get("candidate_name")
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
                                logger.info(f"✅ Interview assessment stored: interview_id={interview.interview_id}, recommendation={recommendation}")
                                
                                # Generate transcript annotations (AI feedback)
                                _rt_ann_lang = conversation.interview_start_language if conversation else None
                                try:
                                    if config.get("llm_provider", DEFAULT_LLM_PROVIDER) == "gpt":
                                        from backend.services.language_llm_openai import generate_transcript_annotations
                                        annotations = generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_rt_ann_lang)
                                    else:
                                        from backend.services.language_llm_openai import generate_transcript_annotations
                                        annotations = generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_rt_ann_lang)
                                    
                                    # Update conversation history with annotations
                                    for i, msg in enumerate(history):
                                        if msg["role"] == "user":
                                            idx_str = str(i)
                                            if idx_str in annotations:
                                                msg["ai_comment"] = annotations[idx_str]
                                    
                                    interview.conversation_history = json.dumps(history)
                                    db.commit()
                                    logger.info("✅ Saved real-time interview transcript annotations")
                                except Exception as e:
                                    logger.error(f"❌ Error generating real-time transcript annotations: {e}")
                                
                            except Exception as e:
                                logger.error(f"❌ Error storing interview assessment: {e}")
                                db.rollback() if 'db' in locals() else None
                            
                            # Send neutral completion message to candidate (no feedback)
                            await websocket.send_json({
                                "type": "assessment",
                                "assessment": "**Interview Completed**\n\nThank you for your time! Our HR team will review your application and get back to you soon.\n\nWe appreciate your interest in this position.",
                                "interview_completed": True,
                                "interview_id": interview.interview_id if 'interview' in locals() and interview else None
                            })
                            
                            # Clean up and close connection
                            if conversation_id in active_conversations:
                                del active_conversations[conversation_id]
                            if conversation_id in session_configs:
                                del session_configs[conversation_id]
                            if conversation_id in interview_start_times:
                                del interview_start_times[conversation_id]
                            cleanup_dedup_cache(conversation_id)
                            
                            logger.info("✅ Interview auto-concluded by AI")
                            
                            # Wait additional time before closing to ensure audio finished
                            logger.info("⏳ Waiting 5 more seconds before closing connection...")
                            await asyncio.sleep(5)
                            
                            # Close WebSocket connection
                            logger.info(f"🔌 Closing WebSocket connection after AI conclusion")
                            await websocket.close(code=1000, reason="Interview concluded by AI")
                            break  # Exit message loop
                            
                        except Exception as e:
                            logger.error(f"❌ Error generating assessment: {e}")
                            # Continue normally if assessment generation fails
    
    except WebSocketDisconnect:
        # Clean up conversation if needed
        if conversation_id and conversation_id in active_conversations:
            del active_conversations[conversation_id]
        if conversation_id and conversation_id in session_configs:
            del session_configs[conversation_id]
        if conversation_id:
            cleanup_dedup_cache(conversation_id)
        if conversation_id and conversation_id in interview_start_times:
            del interview_start_times[conversation_id]
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e)
            })
        except:
            pass


if __name__ == "__main__":
    from backend.config import SERVER_HOST, SERVER_PORT
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
