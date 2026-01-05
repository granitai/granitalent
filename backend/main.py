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
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uvicorn
import uuid

from backend.config import (
    DEFAULT_VOICE_ID, DEFAULT_CARTESIA_VOICE_ID,
    TTS_PROVIDERS, STT_PROVIDERS, LLM_PROVIDERS,
    DEFAULT_TTS_PROVIDER, DEFAULT_STT_PROVIDER, DEFAULT_LLM_PROVIDER
)
from backend.models.conversation import ConversationManager
from backend.models.job_offer import (
    create_job_offer, get_job_offer, get_all_job_offers,
    update_job_offer, delete_job_offer
)
from backend.services.cv_parser import parse_pdf, validate_pdf
from backend.services.cv_evaluator import evaluate_cv_fit
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
from backend.services.gemini_llm import (
    generate_response as gemini_generate_response,
    generate_opening_greeting as gemini_generate_opening_greeting,
    generate_assessment as gemini_generate_assessment,
    generate_audio_check_message as gemini_generate_audio_check,
    generate_name_request_message as gemini_generate_name_request
)
from backend.services.gpt_llm import (
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
# Store session configurations
session_configs: dict = {}
# Store active streaming STT sessions
streaming_stt_sessions: dict = {}
# Store CV evaluations (in production, use database)
cv_evaluations: dict = {}
# Store candidate applications (in production, use database)
candidate_applications: dict = {}


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
        
        if config.get("tts_provider") == "cartesia":
            audio_bytes = tts_func(name_request_text, voice_id, tts_model)
            audio_format = "wav"
        else:  # elevenlabs
            audio_bytes = tts_func(name_request_text, voice_id, tts_model)
            audio_format = "mp3"
        
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
        
        if candidate_name:
            conversation.set_candidate_name(candidate_name, name_spelling)
            logger.info(f"✅ Got candidate name: {candidate_name} (spelling: {name_spelling})")
            
            # Store candidate name in session config for database storage
            if conversation_id and conversation_id in session_configs:
                session_configs[conversation_id]["candidate_name"] = candidate_name
        
        # Move to actual interview phase
        conversation.set_phase(ConversationManager.PHASE_INTERVIEW)
        
        # Generate actual interview greeting
        interview_context = conversation.get_interview_context()
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
        
        if config.get("tts_provider") == "cartesia":
            audio_bytes = tts_func(greeting_text, voice_id, tts_model)
            audio_format = "wav"
        else:  # elevenlabs
            audio_bytes = tts_func(greeting_text, voice_id, tts_model)
            audio_format = "mp3"
        
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
        
        # Evaluate CV
        evaluation_result = evaluate_cv_fit(
            cv_text=cv_text,
            job_offer_description=job_offer.get_full_description(),
            llm_provider=llm_provider or DEFAULT_LLM_PROVIDER,
            llm_model=llm_model
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
        
        # Automatically evaluate CV
        application_id = f"app_{uuid.uuid4().hex[:12]}"
        logger.info(f"📋 Evaluating CV for application: {application_id}")
        evaluation_result = evaluate_cv_fit(
            cv_text=cv_text,
            job_offer_description=job_offer.get_full_description(),
            llm_provider=DEFAULT_LLM_PROVIDER
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


class JobOfferUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    required_skills: Optional[str] = None
    experience_level: Optional[str] = None
    education_requirements: Optional[str] = None
    required_languages: Optional[str] = None
    interview_start_language: Optional[str] = None


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
        interview_start_language=offer.interview_start_language or ""
    )
    db.add(db_job_offer)
    db.commit()
    db.refresh(db_job_offer)
    
    logger.info(f"📝 Created job offer: {db_job_offer.offer_id} - {db_job_offer.title}")
    
    return {
        "offer_id": db_job_offer.offer_id,
        "title": db_job_offer.title,
        "description": db_job_offer.description,
        "required_skills": db_job_offer.required_skills,
        "experience_level": db_job_offer.experience_level,
        "education_requirements": db_job_offer.education_requirements,
        "required_languages": db_job_offer.required_languages,
        "interview_start_language": db_job_offer.interview_start_language,
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
    if search:
        search_filter = or_(
            DBCandidate.full_name.ilike(f"%{search}%"),
            DBCandidate.email.ilike(f"%{search}%")
        )
        query = query.join(DBCandidate).filter(search_filter)
    
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
            "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None
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
    
    # Create interview record
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
        logger.info(f"✅ Interview record created: {interview.interview_id}")
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
    db: Session = Depends(get_db),
    current_admin: DBAdmin = Depends(get_current_admin)
):
    """List all interview invitations and their status."""
    if db is None:
        db = next(get_db())
    
    query = db.query(DBInterview)
    
    if status:
        query = query.filter(DBInterview.status == status)
    if job_offer_id:
        query = query.filter(DBInterview.job_offer_id == job_offer_id)
    
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
            "completed_at": interview.completed_at.isoformat() if interview.completed_at else None
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
        "created_at": interview.created_at.isoformat() if interview.created_at else None,
        "completed_at": interview.completed_at.isoformat() if interview.completed_at else None
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
        
        result.append({
            "application_id": app.application_id,
            "job_offer": {
                "offer_id": job_offer.offer_id if job_offer else None,
                "title": job_offer.title if job_offer else "Unknown",
                "description": job_offer.description if job_offer else ""
            },
            "ai_status": app.ai_status,
            "ai_reasoning": app.ai_reasoning,
            "ai_score": app.ai_score,
            "hr_status": app.hr_status,
            "hr_override_reason": app.hr_override_reason,
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
                "title": job_offer.title if job_offer else "Unknown"
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
            "description": job_offer.description if job_offer else ""
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
                
                # Store language requirements for interview
                required_languages = db_job_offer.required_languages or ""
                interview_start_language = db_job_offer.interview_start_language or ""
            else:
                # Initialize language variables if not set
                required_languages = ""
                interview_start_language = ""
            
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
                        # Get language requirements
                        required_languages = db_job_offer.required_languages or ""
                        interview_start_language = db_job_offer.interview_start_language or ""
                
                candidate_cv_text = evaluation.get("parsed_cv_text", "")
            
            # Ensure we have language variables initialized
            if 'required_languages' not in locals():
                required_languages = ""
            if 'interview_start_language' not in locals():
                interview_start_language = ""
            
            # Create new conversation with job and candidate context
            conversation_id = f"conv_{len(active_conversations)}"
            conversation = ConversationManager(
                job_offer_description=job_offer.get_full_description() if job_offer else None,
                candidate_cv_text=candidate_cv_text,
                job_title=job_offer.title if job_offer else None,
                required_languages=required_languages,
                interview_start_language=interview_start_language
            )
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
                "candidate_name": None  # Will be set during name check
            }
            session_configs[conversation_id] = config
            
            logger.info(f"🚀 New interview started: {conversation_id}")
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
            
            if config["tts_provider"] == "elevenlabs":
                audio_bytes = tts_func(audio_check_text, voice_id, config["tts_model"])
                audio_format = "mp3"
            else:  # cartesia
                audio_bytes = tts_func(audio_check_text, voice_id, config["tts_model"])
                audio_format = "wav"
            
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            await websocket.send_json({
                "type": "greeting",
                "conversation_id": conversation_id,
                "text": audio_check_text,
                "audio": audio_base64,
                "audio_format": audio_format,
                "phase": conversation.get_current_phase()
            })
        
        # Handle messages
        while True:
            message = await websocket.receive()
            
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
                            
                            await websocket.send_json({
                                "type": "assessment",
                                "assessment": assessment
                            })
                        elif not is_interview_phase:
                            logger.warning(f"⚠️ Interview ended during {current_phase} phase - no assessment generated")
                            await websocket.send_json({
                                "type": "assessment",
                                "assessment": "**Interview Ended Early**\n\nThe interview was ended before the actual interview phase began. No assessment can be provided as the conversation was limited to pre-interview checks (audio/name verification)."
                            })
                        else:
                            logger.warning(f"⚠️ Insufficient conversation history for assessment")
                            await websocket.send_json({
                                "type": "assessment",
                                "assessment": "**Insufficient Conversation**\n\nThere was not enough conversation to generate an assessment. Please ensure the interview has sufficient interaction before ending."
                            })
                        
                        # Clean up
                        del active_conversations[conv_id]
                        if conv_id in session_configs:
                            del session_configs[conv_id]
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
                        
                        # Get interview context for contextual responses
                        interview_context = conversation.get_interview_context()
                        
                        llm_start = time.time()
                        interviewer_response = llm_funcs["generate_response"](
                            history[:-1], 
                            user_text, 
                            model_id=llm_model,
                            interview_context=interview_context
                        )
                        llm_duration = time.time() - llm_start
                        logger.info(f"⏱️ LLM took {llm_duration:.2f}s")
                        
                        conversation.add_message("interviewer", interviewer_response)
                        
                        # Text to Speech using selected provider
                        tts_func = get_tts_function(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                        voice_id = get_voice_id(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                        tts_model = config.get("tts_model")
                        
                        tts_start = time.time()
                        if config.get("tts_provider") == "cartesia":
                            response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                            audio_format = "wav"
                        else:  # elevenlabs
                            response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                            audio_format = "mp3"
                        tts_duration = time.time() - tts_start
                        logger.info(f"⏱️ TTS took {tts_duration:.2f}s")
                        
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
                    interview_context = conversation.get_interview_context()
                    llm_provider = config.get("llm_provider", DEFAULT_LLM_PROVIDER)
                    llm_model = config.get("llm_model", LLM_PROVIDERS[llm_provider]["default_model"])
                    
                    llm_start = time.time()
                    interviewer_response = llm_funcs["generate_response"](
                        history[:-1], 
                        user_text, 
                        model_id=llm_model,
                        interview_context=interview_context
                    )
                    llm_duration = time.time() - llm_start
                    logger.info(f"⏱️ LLM took {llm_duration:.2f}s")
                    
                    conversation.add_message("interviewer", interviewer_response)
                    
                    # Text to Speech using selected provider
                    tts_func = get_tts_function(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    voice_id = get_voice_id(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    tts_model = config.get("tts_model")
                    
                    tts_start = time.time()
                    if config.get("tts_provider") == "cartesia":
                        response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                        audio_format = "wav"
                    else:  # elevenlabs
                        response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                        audio_format = "mp3"
                    tts_duration = time.time() - tts_start
                    logger.info(f"⏱️ TTS took {tts_duration:.2f}s")
                    
                    total_duration = time.time() - total_start
                    logger.info(f"⏱️ TOTAL processing time: {total_duration:.2f}s (STT: {stt_duration:.2f}s + LLM: {llm_duration:.2f}s + TTS: {tts_duration:.2f}s)")
                    
                    response_audio_base64 = base64.b64encode(response_audio_bytes).decode('utf-8')
                    
                    await websocket.send_json({
                        "type": "response",
                        "user_text": user_text,
                        "interviewer_text": interviewer_response,
                        "audio": response_audio_base64,
                        "audio_format": audio_format
                    })
            
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
                    interview_context = conversation.get_interview_context()
                    llm_provider = config.get("llm_provider", DEFAULT_LLM_PROVIDER)
                    llm_model = config.get("llm_model", LLM_PROVIDERS[llm_provider]["default_model"])
                    interviewer_response = llm_funcs["generate_response"](
                        history[:-1], 
                        user_text, 
                        model_id=llm_model,
                        interview_context=interview_context
                    )
                    conversation.add_message("interviewer", interviewer_response)
                    
                    # Text to Speech using selected provider
                    tts_func = get_tts_function(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    voice_id = get_voice_id(config.get("tts_provider", DEFAULT_TTS_PROVIDER))
                    tts_model = config.get("tts_model")
                    
                    if config.get("tts_provider") == "cartesia":
                        response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                        audio_format = "wav"
                    else:  # elevenlabs
                        response_audio_bytes = tts_func(interviewer_response, voice_id, tts_model)
                        audio_format = "mp3"
                    
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
