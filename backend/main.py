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

# Global list of phrases that confidently indicate the AI considers the interview finished.
# This list is used dynamically across all streaming/audio endpoint handlers.
CONCLUSION_PHRASES = [
    "this concludes",
    "that concludes",
    "will be processed",
    "thank you for participating",
    "thank you for your participation",
    "reached the end",
    "time is up",
    "we are out of time",
    "we're out of time",
    "thank you for your time",
    "thank you for coming",
    "any questions for me",
    "questions for me",
    "do you have any questions",
    "thank you for this interview",
    "hr team will review your application",
    "hr will review your application",
    "contact you soon",
    "get back to you soon"
]

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
    DEFAULT_VOICE_ID,
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
from backend.services.storage import upload_file as s3_upload, download_file as s3_download, is_s3_enabled
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
from backend.services.language_llm_gemini import (
    generate_response as gemini_generate_response,
    generate_opening_greeting as gemini_generate_opening_greeting,
    generate_assessment as gemini_generate_assessment,
    generate_audio_check_message as gemini_generate_audio_check,
    generate_name_request_message as gemini_generate_name_request
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

# Language name → ISO 639-1 code mapping for STT
LANGUAGE_TO_ISO = {
    "english": "en", "french": "fr", "arabic": "ar", "spanish": "es",
    "german": "de", "italian": "it", "portuguese": "pt", "dutch": "nl",
    "russian": "ru", "chinese": "zh", "japanese": "ja", "korean": "ko",
    "turkish": "tr", "polish": "pl", "swedish": "sv", "danish": "da",
    "norwegian": "no", "finnish": "fi", "czech": "cs", "greek": "el",
    "hindi": "hi", "thai": "th", "vietnamese": "vi", "indonesian": "id",
    "malay": "ms", "romanian": "ro", "hungarian": "hu", "ukrainian": "uk",
    "hebrew": "he", "persian": "fa", "bengali": "bn", "urdu": "ur",
}

def get_language_code(language_name: str) -> str:
    """Convert language name (e.g. 'French') to ISO code (e.g. 'fr')."""
    if not language_name:
        return ""
    # If already a 2-letter code, return as-is
    if len(language_name) <= 3 and language_name.isalpha():
        return language_name.lower()
    return LANGUAGE_TO_ISO.get(language_name.lower().strip(), "")

# Ensure uploads directory exists — use DATA_DIR if set (Docker), else local
_data_dir = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(_data_dir, "uploads")
VIDEOS_DIR = os.path.join(UPLOADS_DIR, "videos")
CVS_DIR = os.path.join(UPLOADS_DIR, "cvs")
os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(CVS_DIR, exist_ok=True)

# Mount uploads directory for static file serving
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
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


def get_tts_function(provider: str = "elevenlabs"):
    """Get the TTS function."""
    return elevenlabs_tts


def get_stt_function(provider: str = "elevenlabs"):
    """Get the STT function."""
    return elevenlabs_stt


def is_streaming_stt_provider(provider: str) -> bool:
    """Check if the STT provider supports/requires streaming mode."""
    return provider == "elevenlabs_streaming"


def get_voice_id(provider: str = "elevenlabs"):
    """Get the default voice ID."""
    return DEFAULT_VOICE_ID


def _retry_on_quota(func, *args, max_retries=3, **kwargs):
    """Retry a function call with exponential backoff on Gemini quota errors."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            err_str = str(e).lower()
            is_quota = "429" in err_str or "quota" in err_str or "resourceexhausted" in err_str or "rate" in err_str
            if is_quota and attempt < max_retries - 1:
                wait = (attempt + 1) * 15  # 15s, 30s, 45s
                logger.warning(f"⏳ Gemini quota hit (attempt {attempt + 1}/{max_retries}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Unreachable")


def get_llm_functions(provider: str = "gemini"):
    """Get the LLM functions (Gemini)."""
    return {
        "generate_response": gemini_generate_response,
        "generate_opening_greeting": gemini_generate_opening_greeting,
        "generate_assessment": gemini_generate_assessment,
        "generate_audio_check": gemini_generate_audio_check,
        "generate_name_request": gemini_generate_name_request
    }


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
    """Get available voices for interview setup."""
    from backend.config import GEMINI_LIVE_VOICES, GEMINI_LIVE_VOICE
    return {
        "gemini_live": {
            "voices": [{"id": k, "name": v} for k, v in GEMINI_LIVE_VOICES.items()],
            "default_voice": GEMINI_LIVE_VOICE,
        },
        "defaults": {
            "tts_provider": DEFAULT_TTS_PROVIDER,
            "stt_provider": DEFAULT_STT_PROVIDER,
            "llm_provider": DEFAULT_LLM_PROVIDER,
        },
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
        import threading
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


@app.get("/api/admin/applications/{application_id}/cv-file")
async def download_cv_file(application_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Download the original CV PDF file for admin preview."""
    from fastapi.responses import Response
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
# Admin Endpoints - Delete (Permanent)
# ============================================================

@app.delete("/api/admin/applications/{application_id}")
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


@app.delete("/api/admin/interviews/{interview_id}")
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


class BulkInterviewRequest(BaseModel):
    interview_ids: list


class BulkArchiveRequest(BaseModel):
    interview_ids: list
    archive: bool = True


class BulkApplicationRequest(BaseModel):
    application_ids: list


class BulkApplicationArchiveRequest(BaseModel):
    application_ids: list
    archive: bool = True


class BulkJobOfferRequest(BaseModel):
    offer_ids: list


@app.post("/api/admin/interviews/bulk-delete")
async def bulk_delete_interviews(body: BulkInterviewRequest, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Permanently delete multiple interviews at once."""
    if not body.interview_ids:
        raise HTTPException(status_code=400, detail="No interview IDs provided")

    deleted = db.query(DBInterview).filter(DBInterview.interview_id.in_(body.interview_ids)).delete(synchronize_session='fetch')
    db.commit()

    logger.info(f"Bulk deleted {deleted} interviews")
    return {"message": f"{deleted} interview(s) deleted successfully", "deleted_count": deleted}


@app.post("/api/admin/interviews/bulk-archive")
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


@app.post("/api/admin/applications/bulk-delete")
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


@app.post("/api/admin/applications/bulk-archive")
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


@app.post("/api/admin/job-offers/bulk-delete")
async def bulk_delete_job_offers(body: BulkJobOfferRequest, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Permanently delete multiple job offers."""
    if not body.offer_ids:
        raise HTTPException(status_code=400, detail="No job offer IDs provided")

    deleted = db.query(DBJobOffer).filter(DBJobOffer.offer_id.in_(body.offer_ids)).delete(synchronize_session='fetch')
    db.commit()

    logger.info(f"Bulk deleted {deleted} job offers")
    return {"message": f"{deleted} job offer(s) deleted successfully", "deleted_count": deleted}


class BulkCandidateRequest(BaseModel):
    candidate_ids: list


@app.post("/api/admin/candidates/bulk-delete")
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


@app.delete("/api/admin/candidates/{candidate_id}")
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
    
    logger.info(f"🗑️ Candidate permanently deleted: {candidate_id}")
    return {"message": "Candidate and all related data deleted successfully"}


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


@app.post("/api/admin/interviews/{interview_id}/regenerate-assessment")
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
            from backend.database import SessionLocal
            db_bg = SessionLocal()
            try:
                from backend.services.gemini_llm import generate_assessment as gen_assess
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
                        from backend.services.language_llm_gemini import generate_transcript_annotations as gem_ann
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

    import threading
    threading.Thread(target=_regen_bg, daemon=True).start()
    return {"message": "Assessment regeneration started. It will be available shortly."}


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


@app.get("/api/admin/interviews/{interview_id}/turn-audio/{audio_key:path}")
async def get_interview_turn_audio(interview_id: str, audio_key: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Serve a per-turn candidate audio WAV file."""
    from fastapi.responses import Response
    interview = db.query(DBInterview).filter(DBInterview.interview_id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    audio_bytes = s3_download(audio_key, local_dir=UPLOADS_DIR)
    if not audio_bytes:
        raise HTTPException(status_code=404, detail="Turn audio not found")
    return Response(content=audio_bytes, media_type="audio/wav")


@app.get("/api/admin/interviews/{interview_id}/video")
async def get_interview_video(interview_id: str, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Get the interview video recording or snapshot metadata."""
    from fastapi.responses import Response, JSONResponse
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


@app.get("/api/admin/interviews/{interview_id}/snapshots/{index}")
async def get_interview_snapshot(interview_id: str, index: int, db: Session = Depends(get_db), current_admin: DBAdmin = Depends(get_current_admin)):
    """Get a specific snapshot image."""
    from fastapi.responses import Response
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
    
    # Always use Gemini for LLM
    llm_provider = "gemini"
    
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
                    from backend.database import SessionLocal
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
                            from backend.services.language_llm_gemini import generate_transcript_annotations as gemini_ann
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

            import threading
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
                import re
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
                
                audio_bytes = output.read()
                audio_key = f"recordings/{interview_id}.mp3"
                s3_upload(audio_bytes, audio_key, content_type="audio/mpeg", local_dir=UPLOADS_DIR)

                # Store key in database (or base64 as fallback for backward compat)
                if is_s3_enabled():
                    interview.recording_audio = f"s3://{audio_key}"
                else:
                    interview.recording_audio = base64.b64encode(audio_bytes).decode('utf-8')
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


class SnapshotUploadRequest(BaseModel):
    email: str
    snapshots: list  # [{timestamp: str, image: str (base64 JPEG)}]


@app.post("/api/candidates/interviews/{interview_id}/snapshots")
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
        import base64
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


class AsyncInterviewEndRequest(BaseModel):
    interview_id: str
    email: str


@app.post("/api/candidates/interviews/{interview_id}/async/end")
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
                from backend.database import SessionLocal
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
                            from backend.services.language_llm_gemini import generate_transcript_annotations as gemini_ann
                            annotations = gemini_ann(conversation_history=_conv_history, model_id=llm_model, feedback_language=_start_lang)
                        else:
                            from backend.services.language_llm_gemini import generate_transcript_annotations as gem_ann
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

        import threading
        threading.Thread(target=_run_assessment_background, daemon=True).start()

    logger.info(f"✅ Marked async interview as completed (assessment generating in background): {interview_id}")

    return {
        "interview_id": interview_id,
        "status": "completed",
        "message": "Interview ended successfully. Assessment is being generated."
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
                            from backend.services.language_llm_gemini import generate_transcript_annotations as gemini_generate_transcript_annotations
                            annotations = gemini_generate_transcript_annotations(conversation_history=history, model_id=llm_model_tl, feedback_language=_tl_ann_lang)
                        else:
                            from backend.services.language_llm_gemini import generate_transcript_annotations as gemini_generate_transcript_annotations
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
            
            # Store session configuration — always Gemini Live for real-time
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
            # GEMINI LIVE MODE — native audio-in/audio-out (always used for real-time)
            # ============================================================
            if True:  # Always use Gemini Live for real-time interviews
                logger.info("🎙️ GEMINI LIVE MODE — real-time audio conversation")
                from backend.services.gemini_live import GeminiLiveSession
                from backend.config import GOOGLE_API_KEY, GEMINI_LIVE_MODEL, GEMINI_LIVE_VOICE, build_interviewer_system_prompt

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

                # Add live-specific instructions
                live_system_prompt += f"""

LIVE CONVERSATION RULES:
- Start by greeting the candidate warmly, then begin the interview.
- Speak naturally and conversationally — this is a real-time voice call.
- Keep responses SHORT (1-3 sentences). Do not monologue.
- Wait for the candidate to finish speaking before responding.
- LANGUAGE: You MUST speak in {interview_start_language or 'the specified language'} unless this is a multi-language interview and it is time to switch.
- CRITICAL RULE — ALWAYS WAIT FOR ANSWERS: Every time you ask a question, you MUST wait for the candidate to respond before doing ANYTHING else. Never ask a question and then immediately follow up with another question, a language switch, or a farewell. The flow is strictly: ask ONE question → STOP and LISTEN → candidate answers → only THEN decide what to do next.
- BACKGROUND NOISE: If you hear only silence, clicks, typing, or background noise without actual speech, do NOT treat it as a response. Simply wait patiently. Only proceed when the candidate says actual words. If the audio input seems like noise rather than speech, say something like "I didn't catch that, could you please repeat?" instead of moving on.
- ENDING THE INTERVIEW: Do NOT end the interview on your own. The system manages timing and language switching. Just keep asking questions and waiting for answers. When the system tells you it is time to end, say a warm goodbye and call end_interview.
- If the candidate explicitly asks to end the interview, you may say goodbye and call end_interview.
- You MUST call end_interview after your farewell — this is how the system knows the interview is over.
- Do NOT wait for the candidate to respond after your farewell — call end_interview right away.
- NEVER ask the candidate if they have any questions. This is a one-way evaluation interview. Just conclude politely and call end_interview."""

                # Add multi-language instructions if applicable
                if len(_req_langs_list) > 1:
                    live_system_prompt += f"""

MULTI-LANGUAGE INTERVIEW — MANDATORY:
- This interview REQUIRES testing the candidate in ALL of these languages: {', '.join(_req_langs_list)}.
- Start in {interview_start_language or _req_langs_list[0]}.
- LANGUAGE SWITCHING: The system will inject a context hint telling you when to switch languages. When you see this hint, incorporate the switch into your NEXT natural response — acknowledge the candidate's answer, then smoothly transition to the new language. Example: respond to their answer briefly, then say (IN THE NEW LANGUAGE) "Let's continue in English" and ask ONE question in the new language.
- CRITICAL: ALWAYS wait for the candidate to fully answer your current question BEFORE switching. The flow is: ask question → WAIT for answer → hear answer → THEN switch in your response. Never switch without hearing the answer first.
- Each question must be asked ENTIRELY in ONE language. Never blend two languages in the same turn.
- When switching, announce the switch IN THE NEW LANGUAGE (not the old one). Your entire response after the switch must be in the new language.
- DO NOT end the interview or call end_interview until the system tells you to. The system handles interview timing automatically.
- DO NOT anticipate or prepare for a language switch. Do not mention upcoming switches. Just ask questions naturally in the current language.
- When speaking a language, speak it natively and fluently — no accent from another language."""

                live_model = GEMINI_LIVE_MODEL
                live_voice = init_data.get("gemini_live_voice", GEMINI_LIVE_VOICE)

                # Determine language code for transcription
                live_lang_code = get_language_code(interview_start_language or "") or "en"
                session = GeminiLiveSession(
                    api_key=GOOGLE_API_KEY,
                    model=live_model,
                    system_prompt=live_system_prompt,
                    voice=live_voice,
                    language=live_lang_code,
                )

                ws_lock = asyncio.Lock()
                output_transcript_buffer = []
                input_flush_task = None
                live_concluded = False
                interview_ending = False  # Set when end_interview is called, live_concluded set after turnComplete
                interview_ending_timer = [None]  # Fallback timer to force live_concluded
                user_is_speaking = False
                ai_is_speaking = False  # True while AI audio is being generated (prevents echo detection)
                echo_cooldown_until = [0.0]  # timestamp until which echo suppression is active (post-turn playback delay)
                # Audio capture: collect all candidate PCM chunks for combined recording + per-turn STT
                all_input_audio_chunks = []    # full recording (base64 PCM chunks)
                turn_input_audio_chunks = []   # per-turn buffer for dedicated STT
                gemini_input_transcript_buffer = []  # Gemini's own input transcription — fallback if ElevenLabs STT fails
                per_turn_audio_data = []       # list of (turn_index, pcm_bytes) for per-answer audio
                turn_counter = [0]             # mutable counter for turn numbering
                # Full interview recording timeline: interleaved candidate (16kHz) + AI (24kHz) audio
                recording_timeline = []        # list of ("input"|"output", base64_pcm_chunk)

                # Track the current expected language for STT
                current_expected_language = interview_start_language or "French"
                current_language_code = live_lang_code  # ISO code like "fr", "en"

                # Multi-language: track AI question count per language for switch timing
                ai_turn_count = [0]                  # total AI turns
                questions_in_current_lang = [0]      # questions in current language
                switch_sent = [False]                 # whether we already sent a switch command this language

                def _transcribe_pcm_with_elevenlabs(pcm_chunks: list, lang_code: str) -> str:
                    """Send buffered PCM audio to ElevenLabs Scribe v2 for high-quality transcription."""
                    import base64, struct, io
                    try:
                        # Merge PCM chunks into raw bytes
                        raw_parts = []
                        for chunk in pcm_chunks:
                            try:
                                raw_parts.append(base64.b64decode(chunk))
                            except Exception:
                                pass
                        if not raw_parts:
                            return ""
                        pcm_data = b"".join(raw_parts)
                        # Need at least 0.3s of audio (16kHz * 2 bytes * 0.3s = 9600 bytes)
                        if len(pcm_data) < 9600:
                            return ""
                        # Build WAV in memory for ElevenLabs API
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
                        # Call ElevenLabs STT with explicit language
                        from backend.services.elevenlabs_stt import speech_to_text as el_stt
                        text = el_stt(wav_bytes, audio_format="wav", language_code=lang_code)
                        return text.strip() if text else ""
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "quota" in error_msg or "429" in error_msg or "account" in error_msg or "limit" in error_msg:
                            logger.warning(f"⚠️ ElevenLabs STT quota/account error: {e} — Gemini inputTranscription will be used as fallback")
                        else:
                            logger.warning(f"ElevenLabs STT failed: {e}")
                        return ""

                async def finalize_user_transcript():
                    """Transcribe buffered user audio via ElevenLabs STT (explicit language) and add to conversation.
                    Falls back to Gemini's inputTranscription if ElevenLabs STT fails (e.g. quota exhausted)."""
                    nonlocal user_is_speaking
                    # Snapshot and clear Gemini transcript buffer regardless of audio chunks
                    gemini_fallback_text = " ".join(gemini_input_transcript_buffer).strip() if gemini_input_transcript_buffer else ""
                    gemini_input_transcript_buffer.clear()

                    if not turn_input_audio_chunks:
                        # No audio chunks but Gemini may have transcribed — use as fallback
                        user_is_speaking = False
                        if gemini_fallback_text and len(gemini_fallback_text) >= 2:
                            logger.info(f"📝 No audio chunks but Gemini transcribed: '{gemini_fallback_text[:80]}...'")
                            cleaned_text = gemini_fallback_text
                            conversation.add_message("candidate", cleaned_text)
                            async with ws_lock:
                                try:
                                    await websocket.send_json({
                                        "type": "live_user_transcript",
                                        "text": cleaned_text,
                                    })
                                except Exception:
                                    pass
                        return
                    # Take a snapshot of the chunks and clear the buffer
                    chunks_to_transcribe = list(turn_input_audio_chunks)
                    turn_input_audio_chunks.clear()
                    user_is_speaking = False
                    if chunks_to_transcribe:
                        # Build per-turn PCM bytes for later upload
                        import base64 as _b64
                        raw_parts = []
                        for chunk in chunks_to_transcribe:
                            try:
                                raw_parts.append(_b64.b64decode(chunk))
                            except Exception:
                                pass
                        turn_pcm = b"".join(raw_parts) if raw_parts else b""

                        # Skip very short audio that's likely noise (less than 0.2s at 16kHz 16-bit mono)
                        if len(turn_pcm) < 6400:
                            logger.debug(f"Skipping very short audio chunk ({len(turn_pcm)} bytes) — likely noise")
                            return

                        # Run ElevenLabs STT in executor (blocking I/O)
                        cleaned_text = await asyncio.get_event_loop().run_in_executor(
                            None, _transcribe_pcm_with_elevenlabs, chunks_to_transcribe, current_language_code
                        )

                        # Fallback to Gemini transcription if ElevenLabs returned nothing
                        if not cleaned_text or len(cleaned_text.strip()) < 2:
                            if gemini_fallback_text and len(gemini_fallback_text) >= 2:
                                logger.warning(f"⚠️ ElevenLabs STT returned empty — falling back to Gemini transcription: '{gemini_fallback_text[:80]}...'")
                                cleaned_text = gemini_fallback_text
                            else:
                                logger.debug(f"Skipping empty/trivial transcription (both ElevenLabs and Gemini empty)")
                                return

                        # Filter out STT artifacts — ElevenLabs returns these for non-speech audio
                        _noise_phrases = {
                            "silence", "(silence)", "[silence]",
                            "blank audio", "(blank audio)", "[blank audio]",
                            "no speech", "(no speech)", "[no speech]",
                            "inaudible", "(inaudible)", "[inaudible]",
                            "background noise", "(background noise)", "[background noise]",
                            "bruit de fond", "(bruit de fond)",
                            "musique", "(musique)", "music", "(music)",
                        }
                        if cleaned_text.strip().lower() in _noise_phrases:
                            logger.debug(f"Skipping STT noise artifact: '{cleaned_text}'")
                            return
                        # Save per-turn audio data for later upload
                        turn_idx = turn_counter[0]
                        turn_counter[0] += 1
                        if len(turn_pcm) >= 9600:  # at least 0.3s of audio
                            per_turn_audio_data.append((turn_idx, turn_pcm))
                            conversation.add_message("candidate", cleaned_text, audio_turn=turn_idx)
                        else:
                            conversation.add_message("candidate", cleaned_text)
                        # Send finalized user text to frontend
                        async with ws_lock:
                            try:
                                await websocket.send_json({
                                    "type": "live_user_transcript",
                                    "text": cleaned_text,
                                })
                            except Exception:
                                pass


                async def schedule_input_flush():
                    """Wait for a pause in user speech, then finalize."""
                    nonlocal input_flush_task
                    await asyncio.sleep(2.0)
                    await finalize_user_transcript()
                    input_flush_task = None

                async def on_live_audio(pcm_base64: str):
                    nonlocal ai_is_speaking
                    ai_is_speaking = True
                    # Don't play or record AI audio after end_interview was called
                    # (Gemini may generate a duplicate farewell from the toolResponse ack)
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

                async def on_live_input_transcription(text: str):
                    """Gemini's transcription of user speech — used as 'user is speaking' signal
                    AND as fallback transcript if ElevenLabs STT fails (e.g. quota exhausted)."""
                    nonlocal input_flush_task, user_is_speaking
                    if not text or not text.strip():
                        return
                    # Ignore input transcription while AI is speaking (echo from speakers)
                    if ai_is_speaking:
                        return
                    # Ignore echo from speakers still playing after AI turn completed
                    import time as _time_mod
                    if _time_mod.time() < echo_cooldown_until[0]:
                        return
                    # Accumulate Gemini's transcription as fallback for ElevenLabs STT
                    gemini_input_transcript_buffer.append(text.strip())
                    # Notify frontend that user is speaking (only once per speaking turn)
                    if not user_is_speaking:
                        user_is_speaking = True
                        async with ws_lock:
                            try:
                                await websocket.send_json({"type": "user_speaking", "speaking": True})
                            except Exception:
                                pass
                    # Reset the debounce timer — when user stops speaking for 2s, finalize via ElevenLabs STT
                    if input_flush_task:
                        input_flush_task.cancel()
                    input_flush_task = asyncio.create_task(schedule_input_flush())

                async def on_live_interview_end(reason: str):
                    """Called when Gemini invokes the end_interview function.
                    Returns False to reject if not enough questions asked or untested languages remain.
                    Uses two-phase shutdown: sets interview_ending first, then live_concluded
                    only after the next turnComplete processes the last user answer."""
                    nonlocal interview_ending
                    logger.info(f"🔔 end_interview called: reason={reason}, ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()}, q_in_lang={questions_in_current_lang[0]}")

                    # Guard 1: reject premature ending — need at least 4 AI turns
                    # (unless candidate explicitly requested to end)
                    if reason != "candidate_requested" and ai_turn_count[0] < 4:
                        logger.warning(f"🚫 Rejected end_interview: only {ai_turn_count[0]} questions asked (minimum 4)")
                        return {"reason": (
                            "REJECTED: The interview has barely started. You have only asked "
                            f"{ai_turn_count[0]} question(s) — the minimum is 4. "
                            "Continue asking questions. Do NOT attempt to end the interview again until you have asked more questions."
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

                    logger.info(f"Gemini Live: end_interview accepted (reason: {reason})")
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
                    """Buffer a language switch instruction into Gemini's context WITHOUT forcing a response.

                    Uses send_context (turnComplete=false) so the instruction is buffered until
                    the candidate next speaks and VAD completes the turn. Gemini then processes
                    the candidate's answer + our hint together, producing ONE natural response
                    that acknowledges the answer AND switches language. No interruption.
                    """
                    try:
                        switch_context_injected[0] = True
                        switch_context_target[0] = target_lang
                        await session.send_context(
                            f"[SYSTEM INSTRUCTION — NOT SPOKEN TO CANDIDATE] "
                            f"IMPORTANT: After the candidate finishes answering your current question, "
                            f"you must switch to {target_lang}. "
                            f"In your NEXT response: briefly acknowledge their answer, then smoothly "
                            f"transition by announcing IN {target_lang} (not the current language) that "
                            f"you will continue in {target_lang}. Then ask ONE question in {target_lang}. "
                            f"CRITICAL: Wait for the candidate's answer first. Do NOT switch immediately. "
                            f"The announcement and question must BOTH be entirely in {target_lang}. "
                            f"From now on, speak ONLY in {target_lang} until told otherwise."
                        )
                        logger.info(f"🔄 Language switch HINT buffered (turnComplete=false): → {target_lang}")
                    except Exception as e:
                        logger.error(f"Failed to buffer language switch hint: {e}")

                async def _force_language_switch(target_lang: str):
                    """Force an immediate language switch by sending turnComplete=true.

                    Used as a fallback when the hint approach didn't work (Gemini ignored the hint).
                    This WILL interrupt the current flow and force Gemini to respond immediately.
                    """
                    nonlocal user_is_speaking, input_flush_task
                    try:
                        injected_language_target[0] = target_lang
                        switch_turn_in_progress[0] = True
                        turn_input_audio_chunks.clear()
                        gemini_input_transcript_buffer.clear()
                        user_is_speaking = False
                        if input_flush_task:
                            input_flush_task.cancel()
                        await session.send_text(
                            f"[SYSTEM INSTRUCTION — NOT SPOKEN TO CANDIDATE] "
                            f"You must now switch to speaking {target_lang}. "
                            f"In your VERY NEXT response: briefly announce IN {target_lang} that "
                            f"you will continue in {target_lang}, then ask ONE question in {target_lang}. "
                            f"The announcement AND question must be entirely in {target_lang}. "
                            f"From now on, speak ONLY in {target_lang} until told otherwise."
                        )
                        logger.info(f"🔄 Language switch FORCED (turnComplete=true): → {target_lang}")
                    except Exception as e:
                        logger.error(f"Failed to force language switch: {e}")

                end_instruction_sent = [False]

                async def _inject_end_instruction():
                    """Tell Gemini it's time to wrap up the interview."""
                    if end_instruction_sent[0] or interview_ending:
                        return
                    end_instruction_sent[0] = True
                    try:
                        await session.send_text(
                            "[SYSTEM INSTRUCTION — NOT SPOKEN TO CANDIDATE] "
                            "You have now asked enough questions in all required languages. "
                            "It is time to end the interview. "
                            "In your NEXT response: thank the candidate warmly for their time, "
                            "say a brief farewell, then call the end_interview function. "
                            "Do NOT ask any more questions. Just say goodbye and call end_interview."
                        )
                        logger.info("📩 End instruction sent to Gemini Live")
                    except Exception as e:
                        logger.error(f"Failed to inject end instruction: {e}")

                async def on_live_turn_complete():
                    nonlocal input_flush_task, current_expected_language, current_language_code, live_concluded, ai_is_speaking, user_is_speaking
                    ai_is_speaking = False
                    # Post-turn echo cooldown: speakers may still be playing buffered audio
                    import time as _time_mod
                    echo_cooldown_until[0] = _time_mod.time() + 1.5
                    # AI finished speaking — finalize any pending user transcript
                    # BUT: skip this if the current turn was a switch response, because
                    # audio accumulated during the switch announcement is echo/noise, not real speech
                    if not switch_turn_in_progress[0]:
                        if input_flush_task:
                            input_flush_task.cancel()
                            input_flush_task = None
                        await finalize_user_transcript()
                    else:
                        # Discard any audio that accumulated during the switch announcement
                        turn_input_audio_chunks.clear()
                        gemini_input_transcript_buffer.clear()
                        user_is_speaking = False
                        if input_flush_task:
                            input_flush_task.cancel()
                            input_flush_task = None
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
                            # Strategy: At Q3, buffer a hint (turnComplete=false) so Gemini
                            # incorporates the switch into its NEXT natural response.
                            # If Gemini ignores the hint by Q5+, force it (turnComplete=true).
                            untested = [l for l in _req_langs_list if l not in conversation.get_tested_languages()]

                            if untested and not switch_sent[0] and not is_forced_switch_turn:
                                if questions_in_current_lang[0] >= 3:
                                    # Buffer the switch hint — does NOT force a response
                                    next_lang = untested[0]
                                    switch_sent[0] = True
                                    logger.info(f"🔄 Buffering language switch hint: {current_expected_language} → {next_lang}")
                                    asyncio.create_task(_hint_language_switch(next_lang))

                            elif untested and switch_context_injected[0] and questions_in_current_lang[0] >= 5:
                                # Hint was ignored for 2+ turns — force the switch
                                next_lang = switch_context_target[0] or untested[0]
                                logger.warning(f"⚠️ Hint was ignored ({questions_in_current_lang[0]} questions in {current_expected_language}), forcing switch → {next_lang}")
                                switch_context_injected[0] = False
                                switch_context_target[0] = None
                                asyncio.create_task(_force_language_switch(next_lang))

                            # All languages tested and enough questions — tell AI to wrap up
                            if not untested and ai_turn_count[0] >= 5 and questions_in_current_lang[0] >= 2 and not interview_ending:
                                logger.info(f"✅ All languages tested, {ai_turn_count[0]} questions asked — injecting end instruction")
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
                    nonlocal ai_is_speaking
                    ai_is_speaking = False
                    import time as _time_mod
                    echo_cooldown_until[0] = _time_mod.time() + 0.5  # shorter cooldown on interruption
                    async with ws_lock:
                        try:
                            await websocket.send_json({"type": "live_interrupted"})
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

                    # Kick off the conversation — Gemini won't speak first on its own
                    candidate_name = conversation.cv_candidate_name or "the candidate"
                    start_language = interview_start_language or "English"
                    await session.send_text(
                        f"The interview has just started. Speak ONLY in {start_language}. "
                        f"Greet {candidate_name} warmly in {start_language} and ask your first question in {start_language}."
                    )
                    logger.info("📢 Sent initial prompt to Gemini Live to start talking")

                    reconnect_attempts = [0]
                    max_reconnects = 2

                    # Live message loop — exits when AI concludes, user ends, or session drops
                    while not live_concluded:
                        if not session.connected:
                            # Check if we should attempt reconnection
                            untested_langs = [l for l in _req_langs_list if l not in conversation.get_tested_languages()] if _req_langs_list and len(_req_langs_list) > 1 else []
                            if not interview_ending and untested_langs and reconnect_attempts[0] < max_reconnects:
                                reconnect_attempts[0] += 1
                                logger.warning(f"⚠️ Gemini Live disconnected with untested languages {untested_langs} — attempting reconnect ({reconnect_attempts[0]}/{max_reconnects})")
                                try:
                                    await session.close()
                                    # Rebuild session with existing conversation context
                                    history_summary = conversation.get_history_for_llm()
                                    context_lines = []
                                    for msg in history_summary[-6:]:  # last 6 messages for context
                                        role = "Interviewer" if msg["role"] == "interviewer" else "Candidate"
                                        context_lines.append(f"{role}: {msg['content'][:200]}")
                                    context_text = "\n".join(context_lines)

                                    session = GeminiLiveSession(
                                        api_key=GOOGLE_API_KEY,
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
                                    logger.info(f"✅ Gemini Live reconnected successfully — switching to {next_lang}")
                                    async with ws_lock:
                                        try:
                                            await websocket.send_json({"type": "live_reconnected"})
                                        except Exception:
                                            pass
                                    continue
                                except Exception as reconn_err:
                                    logger.error(f"❌ Gemini Live reconnect failed: {reconn_err}")
                                    break
                            else:
                                logger.warning(f"⚠️ Gemini Live session disconnected — exiting loop (ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()}, ending={interview_ending})")
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
                                turn_input_audio_chunks.append(data["audio"])
                                recording_timeline.append(("input", data["audio"]))
                                await session.send_audio(data["audio"])
                                # Backup speech detection via PCM audio level
                                # (Gemini inputTranscription can be delayed for first utterance)
                                # Only check when AI is NOT speaking to avoid echo false-positives
                                import time as _time_mod
                                if not user_is_speaking and not ai_is_speaking and _time_mod.time() >= echo_cooldown_until[0]:
                                    try:
                                        import base64 as _b64_detect, struct as _struct_detect
                                        _pcm_raw = _b64_detect.b64decode(data["audio"])
                                        if len(_pcm_raw) >= 4:
                                            _n_samples = len(_pcm_raw) // 2
                                            _samples = _struct_detect.unpack(f'<{_n_samples}h', _pcm_raw[:_n_samples*2])
                                            _rms = (sum(s*s for s in _samples) / _n_samples) ** 0.5
                                            if _rms > 800:  # Speech threshold (silence is ~0-200)
                                                user_is_speaking = True
                                                async with ws_lock:
                                                    try:
                                                        await websocket.send_json({"type": "user_speaking", "speaking": True})
                                                    except Exception:
                                                        pass
                                                # Also start debounce timer like inputTranscription does
                                                if input_flush_task:
                                                    input_flush_task.cancel()
                                                input_flush_task = asyncio.create_task(schedule_input_flush())
                                    except Exception:
                                        pass
                            elif msg_type == "end_interview":
                                logger.info(f"👤 User ended Gemini Live interview (ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()})")
                                break
                        elif "bytes" in message:
                            pass
                except Exception as e:
                    err_str = str(e).lower()
                    if "disconnect" in err_str or "closed" in err_str:
                        logger.info(f"📡 Client disconnected from Gemini Live (ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()}, ending={interview_ending})")
                    else:
                        logger.error(f"Gemini Live error: {e} (ai_turns={ai_turn_count[0]}, tested={conversation.get_tested_languages()})")
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
                        logger.info("⏳ Waiting for final Gemini messages before closing...")
                        await asyncio.sleep(2)

                    # Finalize any pending user transcript BEFORE closing the session
                    if input_flush_task:
                        input_flush_task.cancel()
                    await finalize_user_transcript()

                    # Now close the Gemini session
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
                                    from backend.services.gemini_llm import generate_assessment as gen_assess
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
                                    logger.info(f"✅ [BG] Gemini Live assessment stored: {interview_rec.interview_id}")

                                    # Generate transcript annotations
                                    try:
                                        from backend.services.language_llm_gemini import generate_transcript_annotations as gem_ann
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
                                    logger.error(f"❌ [BG] Gemini Live assessment error: {e}")
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
                                logger.error(f"❌ [BG] Gemini Live assessment thread error: {e}")

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
                    logger.info("🔌 Closing WebSocket after Gemini Live session ended")
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
                                                from backend.services.language_llm_gemini import generate_transcript_annotations as gemini_ann
                                                annotations = gemini_ann(conversation_history=_history, model_id=llm_mod, feedback_language=_classic_feedback_lang)
                                            else:
                                                from backend.services.language_llm_gemini import generate_transcript_annotations as gem_ann
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
                            elif config.get("tts_provider") == "cartesia":
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
                                            from backend.services.language_llm_gemini import generate_transcript_annotations as gemini_generate_transcript_annotations
                                            annotations = gemini_generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_ws_ann_lang)
                                        else:
                                            from backend.services.language_llm_gemini import generate_transcript_annotations as gemini_generate_transcript_annotations
                                            annotations = gemini_generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_ws_ann_lang)
                                        
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
                        if config.get("stt_provider") == "cartesia":
                            user_text = stt_func(audio_bytes, audio_format="webm", model_id=stt_model)
                        else:
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
                        elif config.get("tts_provider") == "cartesia":
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
                                        from backend.services.language_llm_gemini import generate_transcript_annotations as gemini_generate_transcript_annotations
                                        annotations = gemini_generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_rt_ann_lang)
                                    else:
                                        from backend.services.language_llm_gemini import generate_transcript_annotations as gemini_generate_transcript_annotations
                                        annotations = gemini_generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_rt_ann_lang)
                                    
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
                        if config.get("stt_provider") == "cartesia":
                            user_text = stt_func(audio_bytes, audio_format="webm", model_id=stt_model)
                        else:
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
                        elif config.get("tts_provider") == "cartesia":
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
                                        from backend.services.language_llm_gemini import generate_transcript_annotations as gemini_generate_transcript_annotations
                                        annotations = gemini_generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_rt_ann_lang)
                                    else:
                                        from backend.services.language_llm_gemini import generate_transcript_annotations as gemini_generate_transcript_annotations
                                        annotations = gemini_generate_transcript_annotations(conversation_history=history, model_id=llm_model, feedback_language=_rt_ann_lang)
                                    
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
