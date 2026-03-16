"""Utility / helper functions for the backend (not route handlers)."""
import hashlib
import json
import logging
import re
import time
from typing import Optional

from backend.config import DEFAULT_VOICE_ID
from backend.state import (
    LANGUAGE_TO_ISO,
    message_dedup_cache,
    MESSAGE_DEDUP_WINDOW,
)

# Import service functions used by provider helpers
from backend.services.elevenlabs_tts import text_to_speech as elevenlabs_tts
from backend.services.elevenlabs_stt import speech_to_text as elevenlabs_stt
from backend.services.language_llm_openai import (
    generate_response as llm_generate_response,
    generate_opening_greeting as llm_generate_opening_greeting,
    generate_assessment as llm_generate_assessment,
    generate_audio_check_message as llm_generate_audio_check,
    generate_name_request_message as llm_generate_name_request,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------

def get_language_code(language_name: str) -> str:
    """Convert language name (e.g. 'French') to ISO code (e.g. 'fr')."""
    if not language_name:
        return ""
    # If already a 2-letter code, return as-is
    if len(language_name) <= 3 and language_name.isalpha():
        return language_name.lower()
    return LANGUAGE_TO_ISO.get(language_name.lower().strip(), "")


# ---------------------------------------------------------------------------
# Audio deduplication
# ---------------------------------------------------------------------------

def get_audio_hash(audio_bytes: bytes) -> str:
    """Generate a simple hash for audio data to detect duplicates."""
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
        logger.warning(f"Duplicate audio message detected for {conversation_id}, ignoring")
        return True

    # Record this message
    cache[audio_hash] = current_time
    return False


def cleanup_dedup_cache(conversation_id: str):
    """Clean up dedup cache when conversation ends."""
    if conversation_id in message_dedup_cache:
        del message_dedup_cache[conversation_id]


# ---------------------------------------------------------------------------
# Assessment extraction
# ---------------------------------------------------------------------------

def extract_detailed_scores(assessment_text: str) -> dict:
    """Extract detailed scores from assessment text.

    Handles both new structured JSON assessments and legacy plain-text assessments.
    Returns: Dictionary with scores and overall score.
    """
    # Try parsing as structured JSON first (new format)
    try:
        parsed = json.loads(assessment_text)
        if isinstance(parsed, dict) and "scores" in parsed:
            scores_data = parsed["scores"]
            result = {
                "technical_skills": scores_data.get("technical_skills", {}).get("score"),
                "job_fit": scores_data.get("job_fit", {}).get("score"),
                "communication": scores_data.get("communication", {}).get("score"),
                "problem_solving": scores_data.get("problem_solving", {}).get("score"),
                "cv_consistency": scores_data.get("cv_consistency", {}).get("score"),
                "linguistic_capacity": {},
                "overall_score": parsed.get("overall_score"),
            }
            for lp in parsed.get("language_proficiency", []):
                if isinstance(lp, dict) and "language" in lp and "score" in lp:
                    result["linguistic_capacity"][lp["language"]] = lp["score"]
            return result
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    # Fallback: regex extraction from plain-text assessment (legacy)
    scores = {
        "technical_skills": None, "job_fit": None, "communication": None,
        "problem_solving": None, "cv_consistency": None,
        "linguistic_capacity": {}, "overall_score": None,
    }
    patterns = {
        "technical_skills": r"(?:technical\s+skills?|technical)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10",
        "job_fit": r"(?:job\s+fit|fit)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10",
        "communication": r"(?:communication\s+skills?|communication)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10",
        "problem_solving": r"(?:problem[-\s]?solving|problem\s+solving)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10",
        "cv_consistency": r"(?:cv\s+consistency|cv\s+vs|cv)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10",
        "overall_score": r"(?:overall\s+score|overall|mean)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10",
    }
    assessment_lower = assessment_text.lower()
    for key, pattern in patterns.items():
        match = re.search(pattern, assessment_lower, re.IGNORECASE)
        if match:
            try:
                scores[key] = float(match.group(1))
            except Exception:
                pass
    language_pattern = r"(\w+)\s*(?:language|proficiency|fluency)\s*[:\-]?\s*(\d+(?:\.\d+)?)/10"
    for match in re.finditer(language_pattern, assessment_lower, re.IGNORECASE):
        language = match.group(1).capitalize()
        try:
            scores["linguistic_capacity"][language] = float(match.group(2))
        except Exception:
            pass
    if scores["overall_score"] is None:
        valid = [v for v in [scores["technical_skills"], scores["job_fit"], scores["communication"], scores["problem_solving"], scores["cv_consistency"]] if v is not None]
        if valid:
            scores["overall_score"] = sum(valid) / len(valid)
    return scores


def extract_recommendation(assessment_text: str) -> Optional[str]:
    """Extract recommendation from assessment text.

    Handles both new structured JSON and legacy plain-text formats.
    Returns: 'recommended', 'not_recommended', or None.
    """
    # Try JSON format first
    try:
        parsed = json.loads(assessment_text)
        if isinstance(parsed, dict) and "recommendation" in parsed:
            rec = parsed["recommendation"]
            if rec in ("recommended", "not_recommended", "maybe"):
                return rec if rec != "maybe" else None
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: keyword matching (legacy)
    assessment_lower = assessment_text.lower()
    positive_indicators = ["recommend", "recommended", "strong candidate", "good fit", "would hire", "suitable", "qualified"]
    negative_indicators = ["not recommend", "not recommended", "do not recommend", "would not hire", "not suitable", "not qualified", "poor fit"]

    if "hiring recommendation" in assessment_lower:
        rec_section = assessment_lower.split("hiring recommendation")[-1][:500]
        if any(neg in rec_section for neg in ["not recommend", "do not recommend", "would not"]):
            return "not_recommended"
        elif any(pos in rec_section for pos in ["recommend", "would hire", "suitable"]):
            return "recommended"

    positive_count = sum(1 for i in positive_indicators if i in assessment_lower)
    negative_count = sum(1 for i in negative_indicators if i in assessment_lower)
    if negative_count > positive_count and negative_count > 0:
        return "not_recommended"
    elif positive_count > negative_count and positive_count > 0:
        return "recommended"
    return None


# ---------------------------------------------------------------------------
# Provider helpers
# ---------------------------------------------------------------------------

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
                logger.warning(f"Gemini quota hit (attempt {attempt + 1}/{max_retries}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Unreachable")


def get_llm_functions(provider: str = "openai"):
    """Get the LLM functions (OpenAI)."""
    return {
        "generate_response": llm_generate_response,
        "generate_opening_greeting": llm_generate_opening_greeting,
        "generate_assessment": llm_generate_assessment,
        "generate_audio_check": llm_generate_audio_check,
        "generate_name_request": llm_generate_name_request
    }
