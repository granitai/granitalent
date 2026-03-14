"""
Language-only Gemini LLM service.

This module wraps Google Gemini for language-only evaluation.
Uses centralized prompts from language_prompts.py.
"""

import re
import logging
import json
import google.generativeai as genai
from typing import List, Dict, Optional

from backend.config import GOOGLE_API_KEY, LLM_PROVIDERS, DEFAULT_LLM_PROVIDER, LANGUAGE_LLM_TEMPERATURE, ASSESSMENT_TEMPERATURE, ASSESSMENT_MAX_TOKENS
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

# Configure the Gemini API
genai.configure(api_key=GOOGLE_API_KEY)

# Get default model
DEFAULT_LLM_MODEL = LLM_PROVIDERS[DEFAULT_LLM_PROVIDER]["default_model"]


def clean_response(text: str) -> str:
    """Clean the LLM response by removing role prefixes."""
    text = re.sub(r'^(Interviewer\s*:\s*)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^(Evaluator\s*:\s*)', '', text, flags=re.IGNORECASE)
    return text.strip()


def generate_response(
    conversation_history: List[Dict[str, str]], 
    user_message: str,
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None
) -> str:
    """
    Generate a language evaluation response using Gemini LLM.
    
    Args:
        conversation_history: List of previous messages
        user_message: The current user message
        model_id: The Gemini model to use
        interview_context: Context with languages, timing, etc.
    
    Returns:
        The generated response text
    """
    if model_id is None:
        model_id = DEFAULT_LLM_MODEL
    
    logger.info(f"🌐 Language LLM (Gemini): Using model '{model_id}'")
    
    model = genai.GenerativeModel(model_id)
    
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
        logger.info(f"🌐 Language evaluation for: {interview_context.get('job_title', 'Unknown')}")
    else:
        system_prompt = build_language_evaluator_prompt()
    
    # Get current language for response
    current_language = interview_context.get("current_language") if interview_context else None
    interview_start_language = interview_context.get("interview_start_language") if interview_context else None
    language_to_use = current_language or interview_start_language or "English"
    
    # Build conversation context
    prompt_parts = [
        system_prompt,
        f"\n\nRESPOND ENTIRELY IN {language_to_use.upper()}.",
        "Remember: ONE language per message. No mixing.",
        "No prefix like 'Evaluator:' or 'Interviewer:'.\n"
    ]
    
    # Add conversation history
    for msg in conversation_history:
        role_prefix = "Evaluator" if msg["role"] == "assistant" else "Candidate"
        prompt_parts.append(f"{role_prefix}: {msg['content']}")
    
    # Add current user message
    prompt_parts.append(f"Candidate: {user_message}")
    
    # Add time awareness
    if interview_context:
        time_remaining = interview_context.get("time_remaining_minutes")
        if time_remaining is not None:
            if time_remaining <= 0:
                prompt_parts.append(f"\n⏱️ TIME IS UP! Conclude now in {language_to_use}.")
            elif time_remaining <= 2:
                prompt_parts.append(f"\n⏱️ {time_remaining:.1f} min left - wrap up in {language_to_use}.")
    
    prompt_parts.append(f"\nRespond as language evaluator in {language_to_use} (no prefix):")
    
    # Generate response
    full_prompt = "\n\n".join(prompt_parts)
    response = model.generate_content(
        full_prompt,
        generation_config=genai.types.GenerationConfig(temperature=LANGUAGE_LLM_TEMPERATURE)
    )
    
    cleaned = clean_response(response.text)
    logger.info(f"🌐 Language LLM response: '{cleaned[:50]}...'")
    
    return cleaned


def generate_audio_check_message(model_id: Optional[str] = None, language: Optional[str] = None) -> str:
    """Generate the audio check message."""
    if model_id is None:
        model_id = DEFAULT_LLM_MODEL
    
    logger.info(f"🌐 Language LLM: Audio check in '{language or 'English'}'")
    
    model = genai.GenerativeModel(model_id)
    prompt = get_audio_check_prompt(language)
    response = model.generate_content(prompt)
    
    return clean_response(response.text)


def generate_name_request_message(model_id: Optional[str] = None, language: Optional[str] = None) -> str:
    """Generate the name request message."""
    if model_id is None:
        model_id = DEFAULT_LLM_MODEL
    
    logger.info(f"🌐 Language LLM: Name request in '{language or 'English'}'")
    
    model = genai.GenerativeModel(model_id)
    prompt = get_name_request_prompt(language)
    response = model.generate_content(prompt)
    
    return clean_response(response.text)


def generate_opening_greeting(
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None,
    candidate_name: Optional[str] = None
) -> str:
    """Generate an opening greeting for the language evaluation."""
    if model_id is None:
        model_id = DEFAULT_LLM_MODEL
    
    logger.info(f"🌐 Language LLM: Opening greeting")
    
    model = genai.GenerativeModel(model_id)
    
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
    
    response = model.generate_content(prompt)
    return clean_response(response.text)


def generate_assessment(
    conversation_history: List[Dict[str, str]],
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None
) -> str:
    """
    Generate a LANGUAGE-ONLY assessment with CEFR levels.
    
    Args:
        conversation_history: The full conversation history
        model_id: The Gemini model to use
        interview_context: Context with languages tested, etc.
    
    Returns:
        Language assessment report with CEFR levels
    """
    if model_id is None:
        model_id = DEFAULT_LLM_MODEL
    
    logger.info(f"🌐 Language LLM: Generating CEFR assessment")
    
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
    
    model = genai.GenerativeModel(model_id)
    response = model.generate_content(prompt)
    
    return response.text.strip()


def _parse_annotation_json(content: str) -> Optional[dict]:
    """Parse annotation JSON robustly, handling truncated or malformed responses.

    French feedback often contains apostrophes and special characters that can
    cause issues if the model doesn't escape them properly. Also handles
    truncated responses by salvaging complete key-value pairs.
    """
    import re

    # Remove markdown code fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Clean trailing commas
    fixed = re.sub(r',\s*}', '}', content)
    fixed = re.sub(r',\s*\]', ']', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Try to salvage truncated JSON: find all complete "key": "value" pairs
    # This handles cases where the response was cut off mid-value
    start = fixed.find('{')
    if start == -1:
        return None

    # Extract all complete key-value pairs using regex
    # Matches "digit_key": "any value with escaped quotes"
    pairs = re.findall(r'"(\d+)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*[,}]', fixed[start:])
    if pairs:
        result = {}
        for key, value in pairs:
            # Unescape the value
            try:
                result[key] = json.loads(f'"{value}"')
            except json.JSONDecodeError:
                result[key] = value.replace('\\"', '"').replace('\\n', '\n')
        if result:
            logger.info(f"Salvaged {len(result)} annotation entries from truncated JSON")
            return result

    # Last resort: try to find balanced JSON object
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(fixed)):
        c = fixed[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if not in_string:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(fixed[start:i+1])
                    except json.JSONDecodeError:
                        break

    return None


def generate_transcript_annotations(
    conversation_history: List[Dict[str, str]],
    model_id: Optional[str] = None,
    feedback_language: Optional[str] = None
) -> Dict[str, str]:
    """
    Generate language feedback for each of the candidate's messages in the transcript.

    Args:
        conversation_history: The full conversation history
        model_id: The Gemini model to use
        feedback_language: Language in which to write feedback (e.g. "French")

    Returns:
        A dictionary mapping the message index (as string) to the AI's feedback.
    """
    if model_id is None:
        model_id = DEFAULT_LLM_MODEL

    logger.info(f"🌐 Language LLM (Gemini): Generating transcript language annotations (feedback in {feedback_language or 'English'})")

    # Build transcript with indices
    transcript = []
    for i, msg in enumerate(conversation_history):
        role = "Evaluator" if msg["role"] == "assistant" else "Candidate"
        transcript.append(f"[{i}] {role}: {msg['content']}")

    transcript_text = "\n".join(transcript)

    from backend.services.language_prompts import build_transcript_annotation_prompt
    prompt = build_transcript_annotation_prompt(conversation_transcript=transcript_text, feedback_language=feedback_language)
    
    model = genai.GenerativeModel(model_id)
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=ASSESSMENT_TEMPERATURE,
                max_output_tokens=ASSESSMENT_MAX_TOKENS,
                response_mime_type="application/json"
            )
        )

        content = response.text.strip()
        annotations = _parse_annotation_json(content)
        if annotations is None:
            logger.warning(f"Could not parse annotation JSON, returning empty. Content: {content[:200]}")
            return {}
        return annotations
    except Exception as e:
        logger.error(f"Error generating transcript annotations: {e}")
        return {}
