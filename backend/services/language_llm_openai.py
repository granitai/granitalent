"""
Language-only OpenAI LLM service.

Drop-in replacement for language_llm_gemini.py — same function signatures.
Uses centralized prompts from language_prompts.py.
"""

import re
import logging
import json
from openai import OpenAI
from typing import List, Dict, Optional

from backend.config import (
    OPENAI_API_KEY, LANGUAGE_LLM_TEMPERATURE,
    ASSESSMENT_TEMPERATURE, ASSESSMENT_MAX_TOKENS
)
from backend.services.language_prompts import (
    build_language_evaluator_prompt,
    build_language_assessment_prompt,
    get_audio_check_prompt,
    get_name_request_prompt,
    get_opening_greeting_prompt
)

logger = logging.getLogger(__name__)

DEFAULT_LLM_MODEL = "gpt-4o"

client = OpenAI(api_key=OPENAI_API_KEY)


def clean_response(text: str) -> str:
    """Clean the LLM response by removing role prefixes."""
    text = re.sub(r'^(Interviewer\s*:\s*)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^(Evaluator\s*:\s*)', '', text, flags=re.IGNORECASE)
    return text.strip()


def _chat(messages: list, model: str = None, temperature: float = LANGUAGE_LLM_TEMPERATURE,
          max_tokens: int = 300) -> str:
    """Send a chat completion request to OpenAI."""
    response = client.chat.completions.create(
        model=model or DEFAULT_LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content.strip()


def generate_response(
    conversation_history: List[Dict[str, str]],
    user_message: str,
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None
) -> str:
    """Generate a language evaluation response using OpenAI LLM."""
    model = model_id or DEFAULT_LLM_MODEL
    logger.info(f"🌐 Language LLM (OpenAI): model '{model}'")

    # Build system prompt
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

    current_language = interview_context.get("current_language") if interview_context else None
    interview_start_language = interview_context.get("interview_start_language") if interview_context else None
    language_to_use = current_language or interview_start_language or "English"

    # Build messages
    messages = [
        {"role": "system", "content": system_prompt + f"\n\nRESPOND ENTIRELY IN {language_to_use.upper()}. ONE language per message. No mixing. No prefix."}
    ]
    for msg in conversation_history:
        role = "assistant" if msg["role"] == "assistant" else "user"
        messages.append({"role": role, "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    # Time awareness
    if interview_context:
        time_remaining = interview_context.get("time_remaining_minutes")
        if time_remaining is not None:
            if time_remaining <= 0:
                messages.append({"role": "user", "content": f"[SYSTEM] TIME IS UP! Conclude now in {language_to_use}."})
            elif time_remaining <= 2:
                messages.append({"role": "user", "content": f"[SYSTEM] {time_remaining:.1f} min left - wrap up in {language_to_use}."})

    cleaned = clean_response(_chat(messages, model))
    logger.info(f"🌐 Language LLM response: '{cleaned[:50]}...'")
    return cleaned


def generate_audio_check_message(model_id: Optional[str] = None, language: Optional[str] = None) -> str:
    """Generate the audio check message."""
    logger.info(f"🌐 Language LLM: Audio check in '{language or 'English'}'")
    prompt = get_audio_check_prompt(language)
    messages = [
        {"role": "system", "content": "You are a friendly language evaluator."},
        {"role": "user", "content": prompt}
    ]
    return clean_response(_chat(messages, model_id, max_tokens=100))


def generate_name_request_message(model_id: Optional[str] = None, language: Optional[str] = None) -> str:
    """Generate the name request message."""
    logger.info(f"🌐 Language LLM: Name request in '{language or 'English'}'")
    prompt = get_name_request_prompt(language)
    messages = [
        {"role": "system", "content": "You are a friendly language evaluator."},
        {"role": "user", "content": prompt}
    ]
    return clean_response(_chat(messages, model_id, max_tokens=100))


def generate_opening_greeting(
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None,
    candidate_name: Optional[str] = None
) -> str:
    """Generate an opening greeting for the language evaluation."""
    logger.info(f"🌐 Language LLM: Opening greeting")

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
    messages = [
        {"role": "system", "content": "You are a friendly language evaluator."},
        {"role": "user", "content": prompt}
    ]
    return clean_response(_chat(messages, model_id, max_tokens=300))


def generate_assessment(
    conversation_history: List[Dict[str, str]],
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None
) -> str:
    """Generate a LANGUAGE-ONLY assessment with CEFR levels."""
    model = model_id or DEFAULT_LLM_MODEL
    logger.info(f"🌐 Language LLM (OpenAI): Generating CEFR assessment")

    # Build transcript
    transcript_lines = []
    for msg in conversation_history:
        role = "Evaluator" if msg["role"] == "assistant" else "Candidate"
        transcript_lines.append(f"{role}: {msg['content']}")
    transcript_text = "\n".join(transcript_lines)

    # Get context
    required_languages = interview_context.get("required_languages") if interview_context else None
    tested_languages = interview_context.get("tested_languages", []) if interview_context else []
    candidate_name = interview_context.get("confirmed_candidate_name") if interview_context else None
    job_title = interview_context.get("job_title") if interview_context else None

    prompt = build_language_assessment_prompt(
        conversation_transcript=transcript_text,
        required_languages=required_languages,
        tested_languages=tested_languages,
        candidate_name=candidate_name,
        job_title=job_title
    )

    messages = [
        {"role": "system", "content": "You are an expert language proficiency assessor."},
        {"role": "user", "content": prompt}
    ]
    return _chat(messages, model, temperature=ASSESSMENT_TEMPERATURE, max_tokens=ASSESSMENT_MAX_TOKENS)


def _parse_annotation_json(content: str) -> Optional[dict]:
    """Parse annotation JSON robustly, handling truncated or malformed responses."""
    import re as _re

    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    fixed = _re.sub(r',\s*}', '}', content)
    fixed = _re.sub(r',\s*\]', ']', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    start = fixed.find('{')
    if start == -1:
        return None

    pairs = _re.findall(r'"(\d+)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*[,}]', fixed[start:])
    if pairs:
        result = {}
        for key, value in pairs:
            try:
                result[key] = json.loads(f'"{value}"')
            except json.JSONDecodeError:
                result[key] = value.replace('\\"', '"').replace('\\n', '\n')
        if result:
            return result

    return None


def generate_transcript_annotations(
    conversation_history: List[Dict[str, str]],
    model_id: Optional[str] = None,
    feedback_language: Optional[str] = None
) -> Dict[str, str]:
    """Generate language feedback for each candidate message."""
    model = model_id or DEFAULT_LLM_MODEL
    logger.info(f"🌐 Language LLM (OpenAI): Generating annotations (feedback in {feedback_language or 'English'})")

    transcript_lines = []
    for i, msg in enumerate(conversation_history):
        role = "Evaluator" if msg["role"] == "assistant" else "Candidate"
        transcript_lines.append(f"[{i}] {role}: {msg['content']}")
    transcript_text = "\n".join(transcript_lines)

    from backend.services.language_prompts import build_transcript_annotation_prompt
    prompt = build_transcript_annotation_prompt(
        conversation_transcript=transcript_text,
        feedback_language=feedback_language
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an expert language evaluator. Respond in JSON format only."},
                {"role": "user", "content": prompt}
            ],
            temperature=ASSESSMENT_TEMPERATURE,
            max_tokens=ASSESSMENT_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content.strip()
        annotations = _parse_annotation_json(content)
        if annotations is None:
            logger.warning(f"Could not parse annotation JSON: {content[:200]}")
            return {}
        return annotations
    except Exception as e:
        logger.error(f"Error generating transcript annotations: {e}")
        return {}
