"""FastAPI application for AI Interviewer."""
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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form, Depends, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uvicorn
import uuid

from backend.config import (
    DEFAULT_VOICE_ID, DEFAULT_CARTESIA_VOICE_ID,
    TTS_PROVIDERS, STT_PROVIDERS, LLM_PROVIDERS,
    DEFAULT_TTS_PROVIDER, DEFAULT_STT_PROVIDER, DEFAULT_LLM_PROVIDER,
    INTERVIEW_TIME_LIMIT_MINUTES
)
from backend.models.conversation import ConversationManager
from backend.models.job_offer import (
    create_job_offer, get_job_offer, get_all_job_offers,
    update_job_offer, delete_job_offer
)
from backend.services.cv_parser import parse_pdf, validate_pdf
from backend.services.language_evaluator import evaluate_cv_fit
from backend.database import init_db, get_db
from backend.models.db_models import (
    JobOffer as DBJobOffer,
    Candidate as DBCandidate,
    Application as DBApplication,
    CVEvaluation as DBCVEvaluation,
    Interview as DBInterview,
    Admin as DBAdmin
)
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func
from backend.auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_admin,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from datetime import timedelta

# Import all service modules
from backend.services.elevenlabs_tts import text_to_speech as elevenlabs_tts
from backend.services.elevenlabs_stt import speech_to_text as elevenlabs_stt
from backend.services.elevenlabs_stt_streaming import ElevenLabsSTTStreaming
from backend.services.cartesia_tts import text_to_speech as cartesia_tts
from backend.services.cartesia_stt import speech_to_text as cartesia_stt
from backend.services.language_llm_gemini import (
    generate_response as gemini_generate_response,
    generate_opening_greeting as gemini_generate_opening_greeting,
    generate_assessment as gemini_generate_assessment,
    generate_audio_check_message as gemini_generate_audio_check,
    generate_name_request_message as gemini_generate_name_request
)
from backend.services.language_llm_gpt import (
    generate_response as gpt_generate_response,
    generate_opening_greeting as gpt_generate_opening_greeting,
    generate_assessment as gpt_generate_assessment,
    generate_audio_check_message as gpt_generate_audio_check,
    generate_name_request_message as gpt_generate_name_request
)

app = FastAPI(title="AI Interviewer API")

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database tables on application startup."""
    try:
        init_db()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.warning(f"⚠️ Database initialization warning: {e} (continuing with in-memory storage)")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active conversations (in production, use Redis or database)
active_conversations: dict = {}

# Ensure uploads directory exists
os.makedirs("uploads/videos", exist_ok=True)

# Mount uploads directory for static file serving
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
# Store session configurations
session_configs: dict = {}
# Store active streaming STT sessions
streaming_stt_sessions: dict = {}
# Store interview start times for time limit tracking
interview_start_times: dict = {}
# Store CV evaluations (in production, use database)
cv_evaluations: dict = {}
# Store candidate applications (in production, use database)
candidate_applications: dict = {}
# Store last processed message hashes to prevent duplicates (conversation_id -> {hash: timestamp})
message_dedup_cache: dict = {}
# Deduplication window in seconds
MESSAGE_DEDUP_WINDOW = 5.0


def get_audio_hash(audio_bytes: bytes) -> str:
    """Generate a simple hash for audio data to detect duplicates."""
    import hashlib
    # Use first 1000 bytes for faster hashing while still being unique enough
    sample = audio_bytes[:1000] if len(audio_bytes) > 1000 else audio_bytes
    return hashlib.md5(sample + str(len(audio_bytes)).encode()).hexdigest()


def is_duplicate_message(conversation_id: str, audio_bytes: bytes) -> bool:
    """Check if this audio message is a duplicate within the dedup window."""
    audio_hash = get_audio_hash(audio_bytes)
    current_time = time.time()
    
    # Initialize cache for conversation if not exists
    if conversation_id not in message_dedup_cache:
        message_dedup_cache[conversation_id] = {}
    
    cache = message_dedup_cache[conversation_id]
    
    # Clean up old entries
    old_hashes = [h for h, t in cache.items() if current_time - t > MESSAGE_DEDUP_WINDOW]
    for h in old_hashes:
        del cache[h]
    
    # Check if this is a duplicate
    if audio_hash in cache:
        logger.warning(f"⚠️ Duplicate audio message detected for {conversation_id}, ignoring")
        return True
    
    # Record this message
    cache[audio_hash] = current_time
    return False


def cleanup_dedup_cache(conversation_id: str):
    """Clean up dedup cache when conversation ends."""
    if conversation_id in message_dedup_cache:
        del message_dedup_cache[conversation_id]


def extract_detailed_scores(assessment_text: str) -> dict:
    """
    Extract detailed scores from assessment text.
    Parses scores for each evaluation axis and linguistic capacity.
    Returns: Dictionary with scores and overall score
    """
    scores = {
        "technical_skills": None,
        "job_fit": None,
        "communication": None,
        "problem_solving": None,
        "cv_consistency": None,
        "linguistic_capacity": {},
        "overall_score": None
    }
    
    # Try to extract scores using regex patterns
    patterns = {
        "technical_skills": r"(?:technical\s+skills?|technical)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10",
        "job_fit": r"(?:job\s+fit|fit)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10",
        "communication": r"(?:communication\s+skills?|communication)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10",
        "problem_solving": r"(?:problem[-\s]?solving|problem\s+solving)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10",
        "cv_consistency": r"(?:cv\s+consistency|cv\s+vs|cv)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10",
        "overall_score": r"(?:overall\s+score|overall|mean)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10"
    }
    
    assessment_lower = assessment_text.lower()
    
    for key, pattern in patterns.items():
        match = re.search(pattern, assessment_lower, re.IGNORECASE)
        if match:
            try:
                scores[key] = float(match.group(1))
            except:
                pass
    
    # Extract linguistic capacity scores
    # Look for language-specific scores
    language_pattern = r"(\w+)\s*(?:language|proficiency|fluency)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10"
    language_matches = re.finditer(language_pattern, assessment_lower, re.IGNORECASE)
    for match in language_matches:
        language = match.group(1).capitalize()
        try:
            score = float(match.group(2))
            scores["linguistic_capacity"][language] = score
        except:
            pass
    
    # Calculate overall score if not found but other scores are available
    if scores["overall_score"] is None:
        axis_scores = [
            scores["technical_skills"],
            scores["job_fit"],
            scores["communication"],
            scores["problem_solving"],
            scores["cv_consistency"]
        ]
        valid_scores = [s for s in axis_scores if s is not None]
        if valid_scores:
            scores["overall_score"] = sum(valid_scores) / len(valid_scores)
    
    return scores


def extract_recommendation(assessment_text: str) -> Optional[str]:
    """
    Extract recommendation from assessment text.
    Looks for keywords like 'recommend', 'not recommend', etc.
    Returns: 'recommended', 'not_recommended', or None
    """
    assessment_lower = assessment_text.lower()
    
    # Look for positive recommendation indicators
    positive_indicators = [
        "recommend", "recommended", "strong candidate", "good fit",
        "would hire", "suitable", "qualified", "excellent candidate"
    ]
    
    # Look for negative recommendation indicators
    negative_indicators = [
        "not recommend", "not recommended", "do not recommend",
        "would not hire", "not suitable", "not qualified", "poor fit",
        "lack of", "insufficient", "concerns"
    ]
    
    # Count positive vs negative indicators
    positive_count = sum(1 for indicator in positive_indicators if indicator in assessment_lower)
    negative_count = sum(1 for indicator in negative_indicators if indicator in assessment_lower)
    
    # Check for explicit "Hiring Recommendation" section
    if "hiring recommendation" in assessment_lower:
        rec_section = assessment_lower.split("hiring recommendation")[-1][:500]
        if any(neg in rec_section for neg in ["not recommend", "do not recommend", "would not"]):
            return "not_recommended"
        elif any(pos in rec_section for pos in ["recommend", "would hire", "suitable"]):
            return "recommended"
    
    # Decision based on counts
    if negative_count > positive_count and negative_count > 0:
        return "not_recommended"
    elif positive_count > negative_count and positive_count > 0:
        return "recommended"
    
    return None


def get_tts_function(provider: str):
    """Get the TTS function for the specified provider."""
    if provider == "elevenlabs":
        return elevenlabs_tts
    elif provider == "cartesia":
        return cartesia_tts
    else:
        raise ValueError(f"Unknown TTS provider: {provider}")


def get_stt_function(provider: str):
    """Get the STT function for the specified provider."""
    if provider == "elevenlabs" or provider == "elevenlabs_streaming":
        return elevenlabs_stt
    elif provider == "cartesia":
        return cartesia_stt
    else:
        raise ValueError(f"Unknown STT provider: {provider}")


def is_streaming_stt_provider(provider: str) -> bool:
    """Check if the STT provider supports/requires streaming mode."""
    return provider == "elevenlabs_streaming"


def get_voice_id(provider: str):
    """Get the default voice ID for the specified TTS provider."""
    if provider == "elevenlabs":
        return DEFAULT_VOICE_ID
    elif provider == "cartesia":
        return DEFAULT_CARTESIA_VOICE_ID
    else:
        return DEFAULT_VOICE_ID


def get_llm_functions(provider: str):
    """Get the LLM functions for the specified provider."""
    if provider == "gemini":
        return {
            "generate_response": gemini_generate_response,
            "generate_opening_greeting": gemini_generate_opening_greeting,
            "generate_assessment": gemini_generate_assessment,
            "generate_audio_check": gemini_generate_audio_check,
            "generate_name_request": gemini_generate_name_request
        }
    elif provider == "gpt":
        return {
            "generate_response": gpt_generate_response,
            "generate_opening_greeting": gpt_generate_opening_greeting,
            "generate_assessment": gpt_generate_assessment,
            "generate_audio_check": gpt_generate_audio_check,
            "generate_name_request": gpt_generate_name_request
        }
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


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
            if config.get("tts_provider") == "cartesia":
                audio_bytes = tts_func(name_request_text, voice_id, tts_model)
                audio_format = "wav"
            else:  # elevenlabs
                audio_bytes = tts_func(name_request_text, voice_id, tts_model)
                audio_format = "mp3"
        except ValueError as e:
            # Quota exceeded or other user-friendly error
            error_msg = str(e)
            logger.error(f"❌ TTS Error: {error_msg}")
            await websocket.send_json({
                "type": "error",
                "message": error_msg
            })
            return False
        except Exception as e:
            error_msg = f"TTS service error: {str(e)}"
            logger.error(f"❌ TTS Error: {error_msg}")
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
            if config.get("tts_provider") == "cartesia":
                audio_bytes = tts_func(greeting_text, voice_id, tts_model)
                audio_format = "wav"
            else:  # elevenlabs
                audio_bytes = tts_func(greeting_text, voice_id, tts_model)
                audio_format = "mp3"
        except ValueError as e:
            # Quota exceeded or other user-friendly error
            error_msg = str(e)
            logger.error(f"❌ TTS Error: {error_msg}")
            await websocket.send_json({
                "type": "error",
                "message": error_msg
            })
            return False
        except Exception as e:
            error_msg = f"TTS service error: {str(e)}"
            logger.error(f"❌ TTS Error: {error_msg}")
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


# ============================================================
# Authentication Endpoints
# ============================================================

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """Admin login endpoint."""
    admin = db.query(DBAdmin).filter(DBAdmin.username == login_data.username).first()
    
    if not admin or not verify_password(login_data.password, admin.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password"
        )
    
    if not admin.is_active:
        raise HTTPException(
            status_code=403,
            detail="Admin account is inactive"
        )
    
    # Update last login
    admin.last_login = datetime.now()
    db.commit()
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": admin.username},
        expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": admin.username
    }


@app.get("/api/auth/me")
async def get_current_user_info(current_admin: DBAdmin = Depends(get_current_admin)):
    """Get current authenticated admin info."""
    return {
        "admin_id": current_admin.admin_id,
        "username": current_admin.username,
        "email": current_admin.email,
        "is_active": current_admin.is_active
    }


@app.get("/api/elevenlabs/status")
async def check_elevenlabs_status():
    """Check ElevenLabs account status and credits."""
    from backend.services.elevenlabs_account_check import check_account_status
    return check_account_status()


@app.get("/api/providers")
async def get_providers():
    """Get available providers and their models."""
    return {
        "tts": {
            provider: {
                "name": config["name"],
                "models": [
                    {"id": model_id, "name": model_name}
                    for model_id, model_name in config["models"].items()
                ],
                "default_model": config["default_model"]
            }
            for provider, config in TTS_PROVIDERS.items()
        },
        "stt": {
            provider: {
                "name": config["name"],
                "models": [
                    {"id": model_id, "name": model_name}
                    for model_id, model_name in config["models"].items()
                ],
                "default_model": config["default_model"]
            }
            for provider, config in STT_PROVIDERS.items()
        },
        "llm": {
            provider: {
                "name": config["name"],
                "models": [
                    {"id": model_id, "name": model_name}
                    for model_id, model_name in config["models"].items()
                ],
                "default_model": config["default_model"]
            }
            for provider, config in LLM_PROVIDERS.items()
        },
        "defaults": {
            "tts_provider": DEFAULT_TTS_PROVIDER,
            "stt_provider": DEFAULT_STT_PROVIDER,
            "llm_provider": DEFAULT_LLM_PROVIDER
        }
    }


# ============================================================
# CV Upload and Evaluation Endpoints
# ============================================================

@app.post("/api/cv/upload")
async def upload_cv(
    file: UploadFile = File(...),
    job_offer_id: str = Form(...),
    llm_provider: Optional[str] = Form(None),
    llm_model: Optional[str] = Form(None)
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
        logger.info(f"📄 Parsed CV content ({len(cv_text)} chars):\n{cv_text[:1000]}...")
        
        logger.info(f"✅ CV evaluation complete: {evaluation_id} - {evaluation_result['status']}")
        
        return evaluation_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing CV: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing CV: {str(e)}")


@app.get("/api/cv/evaluation/{evaluation_id}")
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


@app.get("/api/cv/evaluation/{evaluation_id}/parsed-text")
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


# ============================================================
# Candidate Application Endpoints
# ============================================================

@app.post("/api/candidates/apply")
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
    No signup required - candidates can apply directly.
    """
    try:
        # Validate job offer exists in database
        db_job_offer = db.query(DBJobOffer).filter(DBJobOffer.offer_id == job_offer_id).first()
        if not db_job_offer:
            raise HTTPException(status_code=404, detail="Job offer not found")
        
        # Create a JobOffer object for compatibility with existing code
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
        
        # Parse CV
        cv_text = parse_pdf(file_content)
        
        # Handle cover letter file if provided
        cover_letter_text = ""
        cover_letter_filename = None
        if cover_letter_file:
            cover_letter_filename = cover_letter_file.filename
            cover_letter_content = await cover_letter_file.read()
            # Try to parse if it's a PDF
            if cover_letter_filename.lower().endswith('.pdf'):
                try:
                    cover_letter_text = parse_pdf(cover_letter_content)
                except:
                    cover_letter_text = ""  # If parsing fails, leave empty
            # For DOC/DOCX, we'll just store the filename (text extraction would require additional libraries)
        
        # Automatically evaluate CV - Language evaluator checks if CV has required languages
        application_id = f"app_{uuid.uuid4().hex[:12]}"
        logger.info(f"📋 Evaluating CV for application: {application_id}")
        evaluation_result = evaluate_cv_fit(
            cv_text=cv_text,
            job_offer_description=job_offer.get_full_description(),
            llm_provider=DEFAULT_LLM_PROVIDER,
            required_languages=db_job_offer.required_languages
        )
        
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
            db.flush()  # Get candidate_id
        
        # Create application in database
        application = DBApplication(
            application_id=application_id,
            candidate_id=candidate.candidate_id,
            job_offer_id=job_offer_id,
            cover_letter=cover_letter_text or "",
            cover_letter_filename=cover_letter_filename,
            cv_text=cv_text,
            cv_filename=cv_file.filename,
            ai_status=evaluation_result["status"],
            ai_reasoning=evaluation_result.get("reasoning", ""),
            ai_score=evaluation_result.get("score", 0),
            ai_skills_match=evaluation_result.get("skills_match", 0),
            ai_experience_match=evaluation_result.get("experience_match", 0),
            ai_education_match=evaluation_result.get("education_match", 0),
            hr_status="pending"
        )
        db.add(application)
        
        # Also save CV evaluation
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
        db.add(cv_eval)
        
        db.commit()
        
        # Also store in-memory for backward compatibility
        application_data = {
            "application_id": application_id,
            "job_offer_id": job_offer_id,
            "job_title": job_offer.title,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "linkedin": linkedin,
            "portfolio": portfolio,
            "cover_letter": cover_letter_text,
            "cover_letter_filename": cover_letter_filename,
            "cv_text": cv_text,
            "cv_filename": cv_file.filename,
            "submitted_at": datetime.now().isoformat(),
            "status": "pending",
            "evaluation": evaluation_result,
            "evaluation_status": evaluation_result["status"]
        }
        candidate_applications[application_id] = application_data
        
        logger.info(f"✅ Application submitted: {application_id} for {job_offer.title} by {full_name}")
        logger.info(f"📊 CV Evaluation: {evaluation_result['status']} (score: {evaluation_result.get('score', 'N/A')})")
        
        return {
            "application_id": application_id,
            "status": "submitted",
            "evaluation": {
                "status": evaluation_result["status"],
                "score": evaluation_result.get("score", 0),
                "reasoning": evaluation_result.get("reasoning", "")
            },
            "message": "Application submitted successfully. Your CV has been evaluated."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing application: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error processing application: {str(e)}")


@app.get("/api/candidates/applications/{application_id}")
async def get_application(application_id: str):
    """Get a candidate application by ID."""
    if application_id not in candidate_applications:
        raise HTTPException(status_code=404, detail="Application not found")
    
    application = candidate_applications[application_id].copy()
    # Don't return full CV text in public endpoint
    application.pop("cv_text", None)
    return application


# ============================================================
# Admin Endpoints for Job Offers
# ============================================================

class JobOfferCreate(BaseModel):
    title: str
    description: str
    required_skills: str = ""
    experience_level: str = ""
    education_requirements: str = ""
    required_languages: str = ""  # JSON array string, e.g., '["English", "French"]'
    interview_start_language: str = ""
    interview_duration_minutes: int = 20  # Interview duration in minutes (default 20)
    custom_questions: str = ""  # JSON array of custom questions, e.g., '["What is your experience with X?"]'
    evaluation_weights: str = ""  # JSON object with weights, e.g., '{"technical_skills": 5, "language_proficiency": 10}'
    interview_mode: str = "realtime"  # "realtime" or "asynchronous"


class JobOfferUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    required_skills: Optional[str] = None
    experience_level: Optional[str] = None
    education_requirements: Optional[str] = None
    required_languages: Optional[str] = None
    interview_start_language: Optional[str] = None
    interview_duration_minutes: Optional[int] = None
    custom_questions: Optional[str] = None
    evaluation_weights: Optional[str] = None
    interview_mode: Optional[str] = None


@app.post("/api/admin/job-offers")
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


@app.get("/api/admin/job-offers")
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


@app.get("/api/admin/job-offers/{offer_id}")
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


@app.put("/api/admin/job-offers/{offer_id}")
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


@app.delete("/api/admin/job-offers/{offer_id}")
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


@app.get("/api/job-offers")
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


# ============================================================
# Admin Endpoints - Applications Management
# ============================================================

@app.get("/api/admin/applications")
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
                "title": job_offer.title if job_offer else "Unknown"
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


@app.get("/api/admin/applications/{application_id}")
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
            "description": job_offer.description if job_offer else ""
        },
        "cover_letter": application.cover_letter,
        "cv_text": application.cv_text,
        "cv_filename": application.cv_filename,
        "ai_status": application.ai_status,
        "ai_reasoning": application.ai_reasoning,
        "ai_score": application.ai_score,
        "ai_skills_match": application.ai_skills_match,
        "ai_experience_match": application.ai_experience_match,
        "ai_education_match": application.ai_education_match,
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


@app.get("/api/admin/job-offers/{offer_id}/applications")
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


# ============================================================
# Admin Endpoints - Candidate Archive
# ============================================================

@app.get("/api/admin/candidates")
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


@app.get("/api/admin/candidates/{candidate_email}")
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


# ============================================================
# Admin Endpoints - AI Decision Overrides
# ============================================================

class OverrideRequest(BaseModel):
    hr_status: str  # "selected", "rejected"
    reason: Optional[str] = ""


@app.post("/api/admin/applications/{application_id}/override")
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


@app.post("/api/admin/applications/{application_id}/select")
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


@app.post("/api/admin/applications/{application_id}/reject")
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


# ============================================================
# Admin Endpoints - Archive/Unarchive
# ============================================================

@app.post("/api/admin/applications/{application_id}/archive")
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


@app.post("/api/admin/applications/{application_id}/unarchive")
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


@app.post("/api/admin/interviews/{interview_id}/archive")
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


@app.post("/api/admin/interviews/{interview_id}/unarchive")
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


# ============================================================
# Admin Endpoints - Interview Invitations
# ============================================================

class InterviewInvitationRequest(BaseModel):
    interview_date: Optional[str] = None  # ISO format date string
    notes: Optional[str] = ""


@app.post("/api/admin/applications/{application_id}/send-interview")
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


@app.get("/api/admin/interviews")
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


@app.get("/api/admin/interviews/{interview_id}")
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
        "conversation_history": interview.conversation_history,
        "has_recording": interview.recording_audio is not None,
        "has_video": interview.recording_video is not None,
        "recording_video": interview.recording_video,
        "audio_segments": json.loads(interview.audio_segments) if hasattr(interview, 'audio_segments') and interview.audio_segments else [],
        "created_at": interview.created_at.isoformat() if interview.created_at else None,
        "completed_at": interview.completed_at.isoformat() if interview.completed_at else None
    }


@app.get("/api/admin/interviews/{interview_id}/recording")
async def get_interview_recording(interview_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Get the interview recording audio file."""
    if db is None:
        db = next(get_db())
    
    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    if not interview.recording_audio:
        raise HTTPException(status_code=404, detail="No recording available for this interview")
    
    return {
        "interview_id": interview_id,
        "recording_audio": interview.recording_audio,
        "audio_format": "mp3"
    }


# ============================================================
# Candidate Endpoints - Application and Interview Access
# ============================================================

@app.get("/api/candidates/applications")
async def get_candidate_applications(
    email: str = Query(..., description="Candidate email address"),
    db: Session = Depends(get_db)
):
    """Get all applications for a candidate by email."""
    if db is None:
        db = next(get_db())
    
    # Normalize email: trim whitespace and convert to lowercase for comparison
    email_normalized = email.strip().lower()
    
    logger.info(f"🔍 Searching for applications for email: {email_normalized}")
    
    # Use case-insensitive email comparison
    candidate = db.query(DBCandidate).filter(func.lower(DBCandidate.email) == email_normalized).first()
    if not candidate:
        logger.warning(f"❌ Candidate not found for email: {email_normalized}")
        # Return empty list instead of 404 - candidate might not exist yet
        return []
    
    logger.info(f"✅ Found candidate: {candidate.full_name} (ID: {candidate.candidate_id})")
    
    # Get all applications for this candidate
    applications = db.query(DBApplication).filter(DBApplication.candidate_id == candidate.candidate_id).order_by(DBApplication.submitted_at.desc()).all()
    logger.info(f"📋 Found {len(applications)} applications for candidate")
    
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


@app.get("/api/candidates/interviews")
async def get_candidate_interviews(
    email: str = Query(..., description="Candidate email address"),
    db: Session = Depends(get_db)
):
    """Get all interviews for a candidate by email."""
    if db is None:
        db = next(get_db())
    
    # Normalize email: trim whitespace and convert to lowercase for comparison
    email_normalized = email.strip().lower()
    
    logger.info(f"🔍 Searching for interviews for email: {email_normalized}")
    
    # Use case-insensitive email comparison
    candidate = db.query(DBCandidate).filter(func.lower(DBCandidate.email) == email_normalized).first()
    if not candidate:
        logger.warning(f"❌ Candidate not found for email: {email_normalized}")
        # Return empty list instead of 404 - candidate might not exist yet
        return []
    
    logger.info(f"✅ Found candidate: {candidate.full_name} (ID: {candidate.candidate_id})")
    
    # Get all applications for this candidate
    applications = db.query(DBApplication).filter(DBApplication.candidate_id == candidate.candidate_id).all()
    logger.info(f"📋 Found {len(applications)} applications for candidate")
    
    if not applications:
        return []
    
    application_ids = [app.application_id for app in applications]
    logger.info(f"📋 Application IDs: {application_ids}")
    
    # Get all interviews for these applications
    interviews = db.query(DBInterview).filter(DBInterview.application_id.in_(application_ids)).all()
    logger.info(f"🎤 Found {len(interviews)} interviews for applications")
    
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


@app.get("/api/candidates/interviews/{interview_id}")
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
        "interview_invited_at": application.interview_invited_at.isoformat() if application.interview_invited_at else None
    }


# ============================================================
# Asynchronous Interview Endpoints
# ============================================================

class AsyncInterviewStartRequest(BaseModel):
    interview_id: str
    email: str
    tts_provider: str = "elevenlabs"
    tts_model: str = ""
    stt_provider: str = "elevenlabs"
    stt_model: str = ""
    llm_provider: str = "gpt"  # Use "gpt" instead of "openai" to match config
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


@app.post("/api/candidates/interviews/{interview_id}/async/start")
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
    
    # Normalize provider names (handle "openai" -> "gpt")
    if llm_provider == "openai" or llm_provider == "gpt":
        llm_provider = "gpt"
    
    tts_model = request.tts_model or TTS_PROVIDERS[tts_provider]["default_model"]
    stt_model = request.stt_model or STT_PROVIDERS[stt_provider]["default_model"]
    llm_model = request.llm_model or LLM_PROVIDERS[llm_provider]["default_model"]
    
    # Build interview context
    from backend.config import build_interviewer_system_prompt
    import json
    
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
    
    # Generate opening greeting/question
    llm_funcs = get_llm_functions(llm_provider)
    greeting = llm_funcs["generate_opening_greeting"](
        model_id=llm_model,
        interview_context=interview_context,
        candidate_name=candidate.full_name
    )
    
    # Generate audio for greeting
    tts_func = get_tts_function(tts_provider)
    audio_data = tts_func(greeting, model_id=tts_model, voice_id=None)
    audio_base64 = base64.b64encode(audio_data).decode('utf-8')
    
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
        "status": "in_progress"
    }


@app.post("/api/candidates/interviews/{interview_id}/async/submit-answer")
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
    
    # For LLM, ALWAYS use GPT to avoid Gemini quota issues
    # Force GPT regardless of stored preferences to avoid quota errors
    llm_provider = "gpt"  # Always use GPT to avoid Gemini quota issues
    llm_model = provider_preferences.get("llm_model") or LLM_PROVIDERS[llm_provider]["default_model"]
    
    stored_llm = provider_preferences.get("llm_provider")
    if stored_llm and stored_llm != "gpt" and stored_llm != "openai":
        logger.warning(f"⚠️ Stored LLM provider was '{stored_llm}' but forcing GPT to avoid quota issues")
    
    logger.info(f"📝 Using providers for async interview: LLM={llm_provider}/{llm_model}, TTS={tts_provider}/{tts_model}, STT={stt_provider}/{stt_model}")
    
    # Speech to Text
    stt_func = get_stt_function(stt_provider)
    if stt_provider == "cartesia":
        user_text = stt_func(audio_bytes, audio_format="webm", model_id=stt_model)
    else:
        user_text = stt_func(audio_bytes, model_id=stt_model)
    
    if not user_text.strip():
        raise HTTPException(status_code=400, detail="Could not transcribe audio. Please try again.")
    
    # Add user response to conversation
    conversation_history.append({"role": "user", "content": user_text})
    
    # Build interview context
    from backend.config import build_interviewer_system_prompt
    import json as json_module
    
    required_languages_list = []
    if job_offer.required_languages:
        try:
            required_languages_list = json_module.loads(job_offer.required_languages)
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
        
        # Generate next question or assessment
        # Ensure we're using GPT (safety check)
        if llm_provider != "gpt":
            logger.error(f"❌ CRITICAL: llm_provider is '{llm_provider}' but should be 'gpt'. Forcing GPT.")
            llm_provider = "gpt"
            llm_model = LLM_PROVIDERS[llm_provider]["default_model"]
        
        llm_funcs = get_llm_functions(llm_provider)
        logger.info(f"🔧 Final LLM provider before calling get_llm_functions: {llm_provider}")
        
        # Determine if we should end the interview (after ~5-7 questions)
        should_end = question_count >= 5
        
        if should_end:
            # Generate assessment
            assessment = llm_funcs["generate_assessment"](
                conversation_history=conversation_history,
                model_id=llm_model,
                interview_context=interview_context
            )
            
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
            
            # Update interview
            interview.status = "completed"
            interview.completed_at = datetime.now()
            interview.assessment = assessment
            interview.conversation_history = json.dumps(conversation_history)
            if hasattr(interview, 'audio_segments'):
                interview.audio_segments = json.dumps(audio_segments)
            
            # Determine recommendation
            recommendation = "recommended"  # Default, could be enhanced with LLM analysis
            interview.recommendation = recommendation
            
            # Update application
            application.interview_completed_at = datetime.now()
            application.interview_recommendation = recommendation
            
            db.commit()
            
            logger.info(f"✅ Completed asynchronous interview: {interview_id}")
            
            return {
                "interview_id": interview_id,
                "status": "completed",
                "assessment": assessment,
                "recommendation": recommendation
            }
        else:
            # Generate next question
            next_question = llm_funcs["generate_response"](
                conversation_history=conversation_history[:-1],  # Exclude the just-added user message
                user_message=user_text,
                model_id=llm_model,
                interview_context=interview_context
            )
            
            # Generate audio for question
            tts_func = get_tts_function(tts_provider)
            audio_data = tts_func(next_question, model_id=tts_model, voice_id=None)
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')
            
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
                "status": "in_progress"
            }
    except Exception as e:
        logger.error(f"❌ Error in submit_async_answer: {str(e)}", exc_info=True)
        # Check if conversation history already updated in memory
        if len(conversation_history) > 0 and conversation_history[-1]["role"] == "user":
             # Remove the user message if we couldn't generate response to avoid state mismatch
             conversation_history.pop()
        raise HTTPException(status_code=500, detail=f"Error processing answer: {str(e)}")


@app.post("/api/candidates/interviews/{interview_id}/async/save-recording")
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
                
                # Encode to base64 for storage
                recording_base64 = base64.b64encode(output.read()).decode('utf-8')
                
                # Store in database
                interview.recording_audio = recording_base64
                db.commit()
                
                logger.info(f"✅ Saved combined interview recording for interview: {interview_id} ({len(recording_base64)} chars)")
                
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
    


@app.post("/api/candidates/interviews/{interview_id}/async/upload-video")
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
            
        file_path = f"uploads/videos/{interview_id}.{file_extension}"
        
        # Write file to disk
        with open(file_path, "wb") as buffer:
            content = await video_file.read()
            buffer.write(content)
            
        # Update database record (store relative path for serving)
        # Serving path will be /uploads/videos/{interview_id}.{file_extension}
        interview.recording_video = f"videos/{interview_id}.{file_extension}"
        db.commit()
        
        logger.info(f"✅ Video uploaded successfully for interview {interview_id}: {file_path}")
        
        return {
            "interview_id": interview_id,
            "status": "uploaded",
            "file_path": interview.recording_video,
            "message": "Video uploaded successfully"
        }
    except Exception as e:
        logger.error(f"❌ Error uploading video: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload video: {str(e)}")


class AsyncInterviewEndRequest(BaseModel):
    interview_id: str
    email: str


@app.post("/api/candidates/interviews/{interview_id}/async/end")
async def end_async_interview(
    interview_id: str,
    request: AsyncInterviewEndRequest,
    db: Session = Depends(get_db)
):
    """End an asynchronous interview - generates assessment and marks it as completed."""
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
    
    # Only generate assessment if there's conversation history
    assessment = None
    recommendation = "not_recommended"  # Default if no conversation
    
    if conversation_history and len(conversation_history) > 0:
        try:
            # Get providers from stored preferences or use defaults
            provider_preferences = {}
            try:
                if hasattr(interview, 'provider_preferences') and interview.provider_preferences:
                    try:
                        provider_preferences = json.loads(interview.provider_preferences)
                    except:
                        provider_preferences = {}
            except AttributeError:
                provider_preferences = {}
            
            # For LLM, ALWAYS use GPT to avoid Gemini quota issues
            llm_provider = "gpt"
            llm_model = provider_preferences.get("llm_model") or LLM_PROVIDERS[llm_provider]["default_model"]
            
            logger.info(f"📝 Generating assessment for ended async interview: {interview_id} using LLM={llm_provider}/{llm_model}")
            
            # Build interview context
            from backend.config import build_interviewer_system_prompt
            import json as json_module
            
            required_languages_list = []
            if job_offer.required_languages:
                try:
                    required_languages_list = json_module.loads(job_offer.required_languages)
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
            
            # Generate assessment
            llm_funcs = get_llm_functions(llm_provider)
            assessment = llm_funcs["generate_assessment"](
                conversation_history=conversation_history,
                model_id=llm_model,
                interview_context=interview_context
            )
            
            # Determine recommendation (default to recommended if assessment was generated)
            recommendation = "recommended"
            
            logger.info(f"✅ Generated assessment for ended async interview: {interview_id}")
        except Exception as e:
            logger.error(f"❌ Error generating assessment for ended async interview: {e}")
            # Still mark as completed even if assessment generation fails
            assessment = "**Interview Completed**\n\nThank you for your time! Our HR team will review your application and get back to you soon.\n\nWe appreciate your interest in this position."
    else:
        logger.warning(f"⚠️ No conversation history found for interview {interview_id} - marking as completed without assessment")
        assessment = "**Interview Ended**\n\nThank you for your time! Our HR team will review your application and get back to you soon."
    
    # Update interview with assessment and status
    interview.status = "completed"
    interview.completed_at = datetime.utcnow()
    if assessment:
        interview.assessment = assessment
    interview.recommendation = recommendation
    # Ensure conversation history is saved
    if conversation_history:
        interview.conversation_history = json.dumps(conversation_history)
    
    # Update application
    application.interview_completed_at = datetime.utcnow()
    application.interview_recommendation = recommendation
    
    db.commit()
    
    logger.info(f"✅ Marked async interview as completed with assessment: {interview_id}")
    
    return {
        "interview_id": interview_id,
        "status": "completed",
        "assessment": assessment,
        "recommendation": recommendation,
        "message": "Interview ended successfully"
    }


# ============================================================
# Admin Endpoints - Dashboard Statistics
# ============================================================

@app.get("/api/admin/dashboard/stats")
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


# ============================================================
# Admin Endpoints - Search and Filter
# ============================================================

@app.get("/api/admin/applications/search")
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


@app.get("/api/admin/candidates/search")
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
                    
                    application_id = None
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
        import asyncio
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
            
            # Store session configuration
            config = {
                "tts_provider": init_data.get("tts_provider", DEFAULT_TTS_PROVIDER),
                "tts_model": init_data.get("tts_model", TTS_PROVIDERS[init_data.get("tts_provider", DEFAULT_TTS_PROVIDER)]["default_model"]),
                "stt_provider": init_data.get("stt_provider", DEFAULT_STT_PROVIDER),
                "stt_model": init_data.get("stt_model", STT_PROVIDERS[init_data.get("stt_provider", DEFAULT_STT_PROVIDER)]["default_model"]),
                "llm_provider": init_data.get("llm_provider", DEFAULT_LLM_PROVIDER),
                "llm_model": init_data.get("llm_model", LLM_PROVIDERS[init_data.get("llm_provider", DEFAULT_LLM_PROVIDER)]["default_model"]),
                "evaluation_id": evaluation_id,  # Store for linking (may be None)
                "application_id": application_id,  # Store for linking (may be None)
                "interview_id": interview_id,  # Store for linking (may be None)
                "job_offer_id": job_offer_id,
                "candidate_cv_text": candidate_cv_text,
                "candidate_name": candidate_name_from_cv if 'candidate_name_from_cv' in locals() and candidate_name_from_cv else None,  # CV name (source of truth)
                "interview_duration_minutes": interview_duration_minutes  # Interview duration from job offer
            }
            session_configs[conversation_id] = config
            
            # Track interview start time for time limit
            interview_start_times[conversation_id] = time.time()
            
            logger.info(f"🚀 New interview started: {conversation_id}")
            logger.info(f"⏱️ Time limit: {interview_duration_minutes} minutes")
            logger.info(f"📋 TTS: {config['tts_provider']} / {config['tts_model']}")
            logger.info(f"📋 STT: {config['stt_provider']} / {config['stt_model']}")
            logger.info(f"📋 LLM: {config['llm_provider']} / {config['llm_model']}")
            
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
                if config["tts_provider"] == "elevenlabs":
                    audio_bytes = tts_func(audio_check_text, voice_id, config["tts_model"])
                    audio_format = "mp3"
                else:  # cartesia
                    audio_bytes = tts_func(audio_check_text, voice_id, config["tts_model"])
                    audio_format = "wav"
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
                        
                        # Only generate assessment if we're in the actual interview phase
                        # (not during pre-check phases)
                        current_phase = conv.get_current_phase()
                        is_interview_phase = current_phase == ConversationManager.PHASE_INTERVIEW
                        
                        # Generate assessment only if:
                        # 1. We're in interview phase (not pre-check)
                        # 2. There's enough conversation history
                        if is_interview_phase and len(history) >= 2:
                            logger.info(f"📊 Generating assessment for interview phase conversation")
                            llm_funcs = get_llm_functions(config.get("llm_provider", DEFAULT_LLM_PROVIDER))
                            assessment = llm_funcs["generate_assessment"](
                                history, 
                                model_id=config.get("llm_model", LLM_PROVIDERS[config.get("llm_provider", DEFAULT_LLM_PROVIDER)]["default_model"]),
                                interview_context=interview_context
                            )
                            
                            # Store assessment in database
                            try:
                                db = next(get_db())
                                
                                # Extract recommendation and detailed scores
                                recommendation = extract_recommendation(assessment)
                                detailed_scores = extract_detailed_scores(assessment)
                                
                                # Try to find application_id from evaluation_id
                                application_id = None
                                evaluation_id = config.get("evaluation_id")
                                if evaluation_id:
                                    # Check in-memory first
                                    if evaluation_id in cv_evaluations:
                                        application_id = cv_evaluations[evaluation_id].get("application_id")
                                    
                                    # Also check database
                                    if not application_id:
                                        cv_eval = db.query(DBCVEvaluation).filter(
                                            DBCVEvaluation.evaluation_id == evaluation_id
                                        ).first()
                                        if cv_eval:
                                            application_id = cv_eval.application_id
                                
                                job_offer_id = config.get("job_offer_id")
                                candidate_name = conv.get_candidate_name() or config.get("candidate_name")
                                cv_text = config.get("candidate_cv_text", "")
                                
                                # Create or update interview record
                                interview = None
                                if application_id:
                                    # Try to find existing interview for this application
                                    interview = db.query(DBInterview).filter(
                                        DBInterview.application_id == application_id
                                    ).order_by(DBInterview.created_at.desc()).first()
                                
                                if not interview:
                                    # Create new interview record
                                    interview = DBInterview(
                                        application_id=application_id,
                                        job_offer_id=job_offer_id or "",
                                        candidate_name=candidate_name,
                                        cv_text=cv_text[:5000] if cv_text else None,  # Store first 5000 chars
                                        status="completed",
                                        assessment=assessment,
                                        recommendation=recommendation,
                                        evaluation_scores=json.dumps(detailed_scores),
                                        conversation_history=json.dumps(history),
                                        completed_at=datetime.now()
                                    )
                                    db.add(interview)
                                else:
                                    # Update existing interview
                                    interview.status = "completed"
                                    interview.assessment = assessment
                                    interview.recommendation = recommendation
                                    interview.evaluation_scores = json.dumps(detailed_scores)
                                    interview.conversation_history = json.dumps(history)
                                    interview.completed_at = datetime.now()
                                
                                # Update application if it exists
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
                                
                            except Exception as e:
                                logger.error(f"❌ Error storing interview assessment: {e}")
                                db.rollback() if 'db' in locals() else None
                            
                            # Send neutral message to candidate (assessment is stored in DB for admin)
                            await websocket.send_json({
                                "type": "assessment",
                                "assessment": "**Interview Completed**\n\nThank you for your time! Our HR team will review your application and get back to you soon.\n\nWe appreciate your interest in this position."
                            })
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
                        import asyncio
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
                        logger.info(f"🎤 Starting streaming STT session for {conversation_id}")
                        
                        stt_session = ElevenLabsSTTStreaming(
                            model_id="scribe_v2_realtime",
                            language="en",
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
                    
                    if conversation_id in streaming_stt_sessions:
                        try:
                            audio_bytes = base64.b64decode(audio_data)
                            stt_session = streaming_stt_sessions[conversation_id]["session"]
                            await stt_session.send_audio_chunk(audio_bytes)
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
                        
                        # Wait for final transcript with retries
                        import asyncio
                        user_text = ""
                        max_wait_time = 5.0  # Maximum wait time in seconds (increased for audio conversion)
                        wait_interval = 0.2  # Check every 200ms
                        waited = 0.0
                        
                        while waited < max_wait_time:
                            user_text = stt_session.get_transcript()
                            if user_text.strip():
                                logger.info(f"✅ Received transcript after {waited:.2f}s")
                                break
                            await asyncio.sleep(wait_interval)
                            waited += wait_interval
                        
                        if not user_text.strip():
                            logger.warning(f"⚠️ No transcript received after {waited:.2f}s - checking for partial transcripts")
                        
                        stt_duration = time.time() - stt_start_time
                        logger.info(f"⏱️ Streaming STT took {stt_duration:.2f}s (including speech time)")
                        
                        # Close session
                        await stt_session.close()
                        del streaming_stt_sessions[conversation_id]
                        
                        if not user_text.strip():
                            logger.warning(f"⚠️ No transcript received after {waited:.2f}s")
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
                        
                        # Text to Speech using selected provider
                        tts_func = get_tts_function(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                        voice_id = get_voice_id(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                        tts_model = config.get("tts_model")
                        
                        tts_start = time.time()
                        try:
                            if config.get("tts_provider") == "cartesia":
                                response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                                audio_format = "wav"
                            else:  # elevenlabs
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
                        
                        response_audio_base64 = base64.b64encode(response_audio_bytes).decode('utf-8')
                        
                        await websocket.send_json({
                            "type": "response",
                            "user_text": user_text,
                            "interviewer_text": interviewer_response,
                            "audio": response_audio_base64,
                            "audio_format": audio_format
                        })
                
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
                    if config.get("stt_provider") == "cartesia":
                        user_text = stt_func(audio_bytes, audio_format="webm", model_id=stt_model)
                    else:
                        user_text = stt_func(audio_bytes, model_id=stt_model)
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
                    
                    # Text to Speech using selected provider
                    tts_func = get_tts_function(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    voice_id = get_voice_id(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    tts_model = config.get("tts_model")
                    
                    tts_start = time.time()
                    try:
                        if config.get("tts_provider") == "cartesia":
                            response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                            audio_format = "wav"
                        else:  # elevenlabs
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
                    
                    # Detect if AI concluded the interview
                    conclusion_phrases = [
                        "do you have any questions",
                        "any questions for me",
                        "questions for me",
                        "this concludes our interview",
                        "thank you for your time",
                        "thank you for coming",
                        "that concludes",
                        "we've reached the end",
                        "time is up",
                        "we're out of time"
                    ]
                    response_lower = interviewer_response.lower()
                    is_conclusion = any(phrase in response_lower for phrase in conclusion_phrases)
                    
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
                        import asyncio
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
                    
                    if config.get("stt_provider") == "cartesia":
                        user_text = stt_func(audio_bytes, audio_format="webm", model_id=stt_model)
                    else:
                        user_text = stt_func(audio_bytes, model_id=stt_model)
                    
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
                    
                    # Text to Speech using selected provider
                    tts_func = get_tts_function(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    voice_id = get_voice_id(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    tts_model = config.get("tts_model")
                    
                    try:
                        if config.get("tts_provider") == "cartesia":
                            response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                            audio_format = "wav"
                        else:  # elevenlabs
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
                    
                    response_audio_base64 = base64.b64encode(response_audio_bytes).decode('utf-8')
                    
                    await websocket.send_json({
                        "type": "response",
                        "user_text": user_text,
                        "interviewer_text": interviewer_response,
                        "audio": response_audio_base64,
                        "audio_format": audio_format
                    })
    
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
