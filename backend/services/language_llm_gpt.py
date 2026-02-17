"""
Language-only GPT LLM service.

This module wraps OpenAI GPT for language-only evaluation.
Uses centralized prompts from language_prompts.py.
"""

import re
import logging
import json
from openai import OpenAI
from typing import List, Dict, Optional

from backend.config import OPENAI_API_KEY, LLM_PROVIDERS
from backend.services.language_prompts import (
    build_language_evaluator_prompt,
    build_language_assessment_prompt,
    get_audio_check_prompt,
    get_name_request_prompt,
    get_opening_greeting_prompt
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Default model for GPT
DEFAULT_GPT_MODEL = LLM_PROVIDERS["gpt"]["default_model"]


def clean_response(text: str) -> str:
    """Clean the LLM response by removing role prefixes."""
    text = re.sub(r'^(Interviewer\s*:\s*)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^(Evaluator\s*:\s*)', '', text, flags=re.IGNORECASE)
    return text.strip()


def _get_client():
    """Get OpenAI client."""
    if not OPENAI_API_KEY:
        raise ValueError("OpenAI API key not configured")
    return OpenAI(api_key=OPENAI_API_KEY)


def _normalize_model(model_id: str) -> str:
    """Remove openai/ prefix if present."""
    if model_id and model_id.startswith("openai/"):
        return model_id.replace("openai/", "", 1)
    return model_id


def generate_response(
    conversation_history: List[Dict[str, str]], 
    user_message: str,
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None
) -> str:
    """
    Generate a language evaluation response using GPT.
    
    Args:
        conversation_history: List of previous messages
        user_message: The current user message
        model_id: The GPT model to use
        interview_context: Context with languages, timing, etc.
    
    Returns:
        The generated response text
    """
    if model_id is None:
        model_id = DEFAULT_GPT_MODEL
    
    model_id = _normalize_model(model_id)
    logger.info(f"🌐 Language LLM (GPT): Using model '{model_id}'")
    
    client = _get_client()
    
    # Build the language evaluator prompt
    if interview_context:
        system_prompt = build_language_evaluator_prompt(
            job_title=interview_context.get("job_title"),
            candidate_cv_text=interview_context.get("candidate_cv_text"),
            required_languages=interview_context.get("required_languages"),
            interview_start_language=interview_context.get("interview_start_language"),
            confirmed_candidate_name=interview_context.get("confirmed_candidate_name"),
            time_remaining_minutes=interview_context.get("time_remaining_minutes"),
            total_interview_minutes=interview_context.get("total_interview_minutes"),
            tested_languages=interview_context.get("tested_languages"),
            current_language=interview_context.get("current_language"),
            required_languages_list=interview_context.get("required_languages_list"),
            questions_in_current_language=interview_context.get("questions_in_current_language")
        )
    else:
        system_prompt = build_language_evaluator_prompt()
    
    # Get current language
    current_language = interview_context.get("current_language") if interview_context else None
    interview_start_language = interview_context.get("interview_start_language") if interview_context else None
    language_to_use = current_language or interview_start_language or "English"
    
    # Build messages for GPT
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": f"RESPOND ENTIRELY IN {language_to_use.upper()}. ONE language per message. No mixing. No prefix."}
    ]
    
    # Add conversation history
    for msg in conversation_history:
        role = "assistant" if msg["role"] == "assistant" else "user"
        messages.append({"role": role, "content": msg["content"]})
    
    # Add current message
    messages.append({"role": "user", "content": user_message})
    
    # Generate response
    response = client.chat.completions.create(
        model=model_id,
        messages=messages,
        temperature=0.7,
        max_tokens=500
    )
    
    cleaned = clean_response(response.choices[0].message.content)
    logger.info(f"🌐 Language LLM (GPT) response: '{cleaned[:50]}...'")
    
    return cleaned


def generate_audio_check_message(model_id: Optional[str] = None, language: Optional[str] = None) -> str:
    """Generate the audio check message."""
    if model_id is None:
        model_id = DEFAULT_GPT_MODEL
    
    model_id = _normalize_model(model_id)
    logger.info(f"🌐 Language LLM (GPT): Audio check in '{language or 'English'}'")
    
    client = _get_client()
    prompt = get_audio_check_prompt(language)
    
    response = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=100
    )
    
    return clean_response(response.choices[0].message.content)


def generate_name_request_message(model_id: Optional[str] = None, language: Optional[str] = None) -> str:
    """Generate the name request message."""
    if model_id is None:
        model_id = DEFAULT_GPT_MODEL
    
    model_id = _normalize_model(model_id)
    logger.info(f"🌐 Language LLM (GPT): Name request in '{language or 'English'}'")
    
    client = _get_client()
    prompt = get_name_request_prompt(language)
    
    response = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=150
    )
    
    return clean_response(response.choices[0].message.content)


def generate_opening_greeting(
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None,
    candidate_name: Optional[str] = None
) -> str:
    """Generate an opening greeting for the language evaluation."""
    if model_id is None:
        model_id = DEFAULT_GPT_MODEL
    
    model_id = _normalize_model(model_id)
    logger.info(f"🌐 Language LLM (GPT): Opening greeting")
    
    client = _get_client()
    
    # Extract context
    language = None
    job_title = None
    required_languages = None
    
    if interview_context:
        language = interview_context.get("interview_start_language")
        job_title = interview_context.get("job_title")
        req_langs = interview_context.get("required_languages")
        if req_langs:
            try:
                required_languages = json.loads(req_langs)
            except:
                required_languages = [req_langs]
    
    prompt = get_opening_greeting_prompt(
        language=language,
        candidate_name=candidate_name,
        job_title=job_title,
        required_languages=required_languages
    )
    
    response = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=300
    )
    
    return clean_response(response.choices[0].message.content)


def generate_assessment(
    conversation_history: List[Dict[str, str]],
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None
) -> str:
    """
    Generate a LANGUAGE-ONLY assessment with CEFR levels.
    
    Args:
        conversation_history: The full conversation history
        model_id: The GPT model to use
        interview_context: Context with languages tested, etc.
    
    Returns:
        Language assessment report with CEFR levels
    """
    if model_id is None:
        model_id = DEFAULT_GPT_MODEL
    
    model_id = _normalize_model(model_id)
    logger.info(f"🌐 Language LLM (GPT): Generating CEFR assessment")
    
    client = _get_client()
    
    # Build transcript
    transcript = []
    for msg in conversation_history:
        role = "Evaluator" if msg["role"] == "assistant" else "Candidate"
        transcript.append(f"{role}: {msg['content']}")
    
    transcript_text = "\n".join(transcript)
    
    # Get context
    required_languages = None
    tested_languages = None
    candidate_name = None
    job_title = None
    
    if interview_context:
        required_languages = interview_context.get("required_languages")
        tested_languages = interview_context.get("tested_languages", [])
        candidate_name = interview_context.get("confirmed_candidate_name")
        job_title = interview_context.get("job_title")
    
    # Build assessment prompt
    prompt = build_language_assessment_prompt(
        conversation_transcript=transcript_text,
        required_languages=required_languages,
        tested_languages=tested_languages,
        candidate_name=candidate_name,
        job_title=job_title
    )
    
    response = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000
    )
    
    return response.choices[0].message.content.strip()
