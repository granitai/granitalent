"""OpenAI LLM service for interview question generation and assessment.

Drop-in replacement for gemini_llm.py — same function signatures.
"""
import re
import json
import logging
from openai import OpenAI
from typing import List, Dict, Optional
from backend.config import (
    OPENAI_API_KEY, LLM_TEMPERATURE, LLM_MAX_OUTPUT_TOKENS,
    INTERVIEWER_SYSTEM_PROMPT, build_interviewer_system_prompt,
    ASSESSMENT_TEMPERATURE, ASSESSMENT_MAX_TOKENS
)

logger = logging.getLogger(__name__)

DEFAULT_LLM_MODEL = "gpt-4o"

client = OpenAI(api_key=OPENAI_API_KEY)


def clean_response(text: str) -> str:
    """Clean the LLM response by removing role prefixes."""
    text = re.sub(r'^(Interviewer\s*:\s*)', '', text, flags=re.IGNORECASE)
    return text.strip()


def _chat(messages: list, model: str = None, temperature: float = LLM_TEMPERATURE,
          max_tokens: int = LLM_MAX_OUTPUT_TOKENS) -> str:
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
    """Generate a response using OpenAI LLM."""
    model = model_id or DEFAULT_LLM_MODEL
    logger.info(f"🤖 LLM (OpenAI): model '{model}', msg: '{user_message[:50]}...'")

    # Build system prompt
    if interview_context:
        system_prompt = build_interviewer_system_prompt(
            job_title=interview_context.get("job_title"),
            job_offer_description=interview_context.get("job_offer_description"),
            candidate_cv_text=interview_context.get("candidate_cv_text"),
            required_languages=interview_context.get("required_languages"),
            interview_start_language=interview_context.get("interview_start_language"),
            confirmed_candidate_name=interview_context.get("confirmed_candidate_name"),
            time_remaining_minutes=interview_context.get("time_remaining_minutes"),
            total_interview_minutes=interview_context.get("total_interview_minutes"),
            covered_topics=interview_context.get("covered_topics"),
            tested_languages=interview_context.get("tested_languages"),
            current_language=interview_context.get("current_language"),
            required_languages_list=interview_context.get("required_languages_list"),
            questions_in_current_language=interview_context.get("questions_in_current_language"),
            custom_questions=interview_context.get("custom_questions"),
            evaluation_weights=interview_context.get("evaluation_weights")
        )
    else:
        system_prompt = INTERVIEWER_SYSTEM_PROMPT

    # Get language
    current_language = interview_context.get("current_language") if interview_context else None
    interview_start_language = interview_context.get("interview_start_language") if interview_context else None
    language_to_use = current_language or interview_start_language or "English"

    # Jailbreak detection
    jailbreak_keywords = [
        "ignore previous instructions", "forget you are", "pretend you are",
        "you are now", "roleplay as", "system prompt", "jailbreak", "bypass"
    ]
    if any(kw in user_message.lower() for kw in jailbreak_keywords):
        logger.warning(f"⚠️ Potential jailbreak attempt: {user_message[:50]}...")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f'The candidate said: "{user_message}"\n\n'
                "This seems like they're trying to change the topic. "
                "Politely redirect back to the interview and ask a relevant question."
            )}
        ]
        return clean_response(_chat(messages, model))

    # Build messages
    messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history:
        role = "assistant" if msg["role"] == "assistant" else "user"
        messages.append({"role": role, "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    # Time urgency
    final_instruction = f"Respond in {language_to_use}. No prefix. 2-4 sentences max. Ask ONE new question on a DIFFERENT topic."
    if interview_context:
        time_remaining = interview_context.get("time_remaining_minutes")
        if time_remaining is not None:
            if time_remaining <= 0:
                final_instruction = f"TIME IS UP. Conclude now in {language_to_use}. Thank the candidate."
            elif time_remaining <= 1:
                final_instruction = f"CONCLUDE NOW in {language_to_use}. Thank the candidate briefly."
            elif time_remaining <= 2:
                final_instruction = f"Wrap up in {language_to_use}. Ask if they have questions, then conclude."
    messages.append({"role": "user", "content": f"[SYSTEM] {final_instruction}"})

    cleaned = clean_response(_chat(messages, model))
    logger.info(f"🤖 LLM response: '{cleaned[:50]}...'")
    return cleaned


def generate_audio_check_message(model_id: Optional[str] = None, language: Optional[str] = None) -> str:
    """Generate the initial audio check message."""
    lang = language or "English"
    logger.info(f"🤖 LLM: Audio check in '{lang}'")
    messages = [
        {"role": "system", "content": "You are Granit, a friendly virtual interview assistant from Granitalent."},
        {"role": "user", "content": (
            f"Say a brief, friendly message in {lang} to check if the candidate can hear you. "
            "Introduce yourself as Granit. 1 sentence only, warm and friendly. No prefix."
        )}
    ]
    return clean_response(_chat(messages, model_id, max_tokens=100))


def generate_name_request_message(model_id: Optional[str] = None, language: Optional[str] = None) -> str:
    """Generate the name request message."""
    lang = language or "English"
    logger.info(f"🤖 LLM: Name request in '{lang}'")
    messages = [
        {"role": "system", "content": "You are Granit, a friendly virtual interview assistant from Granitalent."},
        {"role": "user", "content": (
            f"In {lang}, ask the candidate to tell you their name and how it's spelled. "
            "1-2 sentences, warm and friendly. No prefix."
        )}
    ]
    return clean_response(_chat(messages, model_id, max_tokens=100))


def generate_opening_greeting(
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None,
    candidate_name: Optional[str] = None
) -> str:
    """Generate an opening greeting for the interview."""
    logger.info(f"🤖 LLM: Generating greeting")

    if interview_context:
        system_prompt = build_interviewer_system_prompt(
            job_title=interview_context.get("job_title"),
            job_offer_description=interview_context.get("job_offer_description"),
            candidate_cv_text=interview_context.get("candidate_cv_text"),
            required_languages=interview_context.get("required_languages"),
            interview_start_language=interview_context.get("interview_start_language"),
            confirmed_candidate_name=interview_context.get("confirmed_candidate_name"),
            time_remaining_minutes=interview_context.get("time_remaining_minutes"),
            total_interview_minutes=interview_context.get("total_interview_minutes"),
            custom_questions=interview_context.get("custom_questions"),
            evaluation_weights=interview_context.get("evaluation_weights")
        )
        job_title = interview_context.get("job_title", "this position")
        lang = interview_context.get("interview_start_language", "English")
        name_mention = f"Hi {candidate_name}," if candidate_name else "Hi,"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"In {lang}, introduce yourself as Granit from Granitalent, greet the candidate ({name_mention}), "
                f"mention the position ({job_title}), "
                f"briefly note you've reviewed their CV, then ask them to introduce themselves. "
                f"3-4 sentences max. No prefix."
            )}
        ]
    else:
        messages = [
            {"role": "system", "content": INTERVIEWER_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Introduce yourself as Granit from Granitalent, greet the candidate"
                f"{f' ({candidate_name})' if candidate_name else ''} warmly "
                "and ask them to introduce themselves. 2-3 sentences. No prefix."
            )}
        ]

    return clean_response(_chat(messages, model_id, max_tokens=300))


def generate_assessment(
    conversation_history: List[Dict[str, str]],
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None
) -> str:
    """Generate a structured JSON assessment of the interview and candidate.

    Returns a JSON string that can be parsed into a structured assessment object.
    Falls back to a plain text assessment if JSON parsing fails."""
    model = model_id or DEFAULT_LLM_MODEL
    logger.info(f"🤖 LLM (OpenAI): Generating structured assessment with model '{model}'")

    # Filter pre-check messages
    precheck_keywords = ["can you hear me", "do you hear me", "tell me your name", "how it's spelled"]

    meaningful_candidate = [
        m for m in conversation_history
        if m["role"] == "user"
        and len(m["content"].strip()) > 10
        and not any(kw in m["content"].lower() for kw in precheck_keywords)
    ]
    meaningful_interviewer = [
        m for m in conversation_history
        if m["role"] == "assistant"
        and len(m["content"].strip()) > 20
        and not any(kw in m["content"].lower() for kw in precheck_keywords)
    ]

    if len(meaningful_candidate) < 2 or len(meaningful_interviewer) < 2:
        return json.dumps({
            "overall_score": 0,
            "recommendation": "not_recommended",
            "summary": "The interview did not contain sufficient meaningful conversation to provide an evaluation. Please ensure the candidate participates fully.",
            "scores": {
                "technical_skills": {"score": 0, "justification": "No meaningful conversation occurred."},
                "job_fit": {"score": 0, "justification": "No meaningful conversation occurred."},
                "communication": {"score": 0, "justification": "No meaningful conversation occurred."},
                "problem_solving": {"score": 0, "justification": "No meaningful conversation occurred."},
                "cv_consistency": {"score": 0, "justification": "No meaningful conversation occurred."},
            },
            "language_proficiency": [],
            "strengths": [],
            "improvements": ["The candidate did not participate enough in the interview."],
            "custom_questions_coverage": [],
        })

    # Build transcript
    transcript_lines = []
    for msg in conversation_history:
        if any(kw in msg["content"].lower() for kw in precheck_keywords) and len(msg["content"].strip()) < 15:
            continue
        role = "Interviewer" if msg["role"] == "assistant" else "Candidate"
        transcript_lines.append(f"{role}: {msg['content']}")
    transcript_text = "\n".join(transcript_lines)

    # Context
    context_section = ""
    evaluation_weights_dict = {}
    custom_questions_list = []
    if interview_context:
        job_title = interview_context.get("job_title", "Unknown Position")
        job_description = interview_context.get("job_offer_description", "")
        cv_text = interview_context.get("candidate_cv_text", "")
        context_section = f"=== JOB POSITION ===\n{job_title}\n\n{job_description}\n\n=== CANDIDATE CV ===\n{cv_text[:2000]}\n\n"

        eval_weights = interview_context.get("evaluation_weights", "")
        if eval_weights:
            try:
                evaluation_weights_dict = json.loads(eval_weights) if eval_weights else {}
            except Exception:
                pass

        custom_q = interview_context.get("custom_questions", "")
        if custom_q:
            try:
                custom_questions_list = json.loads(custom_q) if custom_q else []
            except Exception:
                pass

    # Language section
    language_instructions = ""
    tested_languages = interview_context.get("tested_languages", []) if interview_context else []
    required_languages = interview_context.get("required_languages") if interview_context else None
    all_languages = []
    if required_languages:
        try:
            all_languages = json.loads(required_languages) if required_languages else []
            tested_list = list(tested_languages) if isinstance(tested_languages, set) else tested_languages
            untested = [l for l in all_languages if l not in tested_list]
            language_instructions = (
                f"\nLanguages tested: {', '.join(tested_list)}\n"
                f"Languages NOT tested (do NOT score these): {', '.join(untested) if untested else 'None'}\n"
                f"For each TESTED language, provide CEFR level (A1-C2) and score (0-10).\n"
            )
        except Exception:
            pass

    # Weights
    weight_instructions = ""
    if evaluation_weights_dict:
        weight_instructions = "\n\nRECRUITER'S EVALUATION PRIORITIES (use as weights for overall score):\n"
        for cat, w in sorted(evaluation_weights_dict.items(), key=lambda x: x[1], reverse=True):
            weight_instructions += f"  - {cat.replace('_', ' ').title()}: {w}/10\n"

    # Custom questions
    custom_section = ""
    if custom_questions_list:
        custom_section = "\n\nRECRUITER'S CUSTOM QUESTIONS — check which were addressed:\n"
        for i, q in enumerate(custom_questions_list, 1):
            custom_section += f"  {i}. {q}\n"

    prompt = f"""You are an expert interview assessor. Evaluate the candidate based ONLY on the transcript below.

CRITICAL — SPEAKER ATTRIBUTION:
- Lines starting with "Interviewer:" are spoken by the AI interviewer (Granit). NEVER attribute these to the candidate.
- Lines starting with "Candidate:" are spoken by the candidate. ONLY evaluate these.
- When quoting evidence, ONLY quote "Candidate:" lines. Never quote "Interviewer:" lines as candidate speech.
- The interviewer's greetings, questions, and comments are NOT the candidate's words.

{context_section}=== INTERVIEW TRANSCRIPT ===
{transcript_text}
{weight_instructions}{custom_section}{language_instructions}
RULES:
- ONLY use evidence from CANDIDATE lines in the transcript. Never quote or attribute Interviewer lines to the candidate.
- Quote specific candidate responses to justify every score. Always prefix quotes with "Candidate:" to show attribution.
- Be fair and thorough.

Respond with a JSON object in EXACTLY this format (no markdown, no code fences, just pure JSON):
{{
  "overall_score": <number 0-10>,
  "recommendation": "<recommended|not_recommended|maybe>",
  "summary": "<2-3 sentence overall assessment>",
  "scores": {{
    "technical_skills": {{
      "score": <0-10>,
      "justification": "<2-3 sentences with direct quotes from transcript>"
    }},
    "job_fit": {{
      "score": <0-10>,
      "justification": "<2-3 sentences with direct quotes>"
    }},
    "communication": {{
      "score": <0-10>,
      "justification": "<2-3 sentences with direct quotes>"
    }},
    "problem_solving": {{
      "score": <0-10>,
      "justification": "<2-3 sentences with direct quotes>"
    }},
    "cv_consistency": {{
      "score": <0-10>,
      "justification": "<2-3 sentences with direct quotes>"
    }}
  }},
  "language_proficiency": [
    {{
      "language": "<language name>",
      "cefr_level": "<A1|A2|B1|B2|C1|C2>",
      "score": <0-10>,
      "details": "<grammar, vocabulary, fluency assessment with 2-3 specific quotes>"
    }}
  ],
  "strengths": ["<strength 1 with transcript evidence>", "<strength 2>"],
  "improvements": ["<area for improvement 1>", "<area 2>"],
  "custom_questions_coverage": [
    {{
      "question": "<the custom question>",
      "answered": <true|false>,
      "summary": "<brief summary of candidate's answer or 'Not addressed'>"
    }}
  ]
}}

Overall score = {"weighted average using recruiter's priorities" if evaluation_weights_dict else "mean of the 5 category scores"}.
Include language_proficiency entries ONLY for languages that were actually tested.
Include custom_questions_coverage ONLY if custom questions were provided ({len(custom_questions_list)} questions)."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an expert interview assessor. Respond with valid JSON only. No markdown, no code fences."},
                {"role": "user", "content": prompt}
            ],
            temperature=ASSESSMENT_TEMPERATURE,
            max_tokens=ASSESSMENT_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        result = response.choices[0].message.content.strip()

        # Validate it's parseable JSON
        parsed = json.loads(result)

        # Ensure required fields exist
        if "overall_score" not in parsed:
            scores = parsed.get("scores", {})
            vals = [v.get("score", 0) for v in scores.values() if isinstance(v, dict)]
            parsed["overall_score"] = round(sum(vals) / max(len(vals), 1), 1)
        if "recommendation" not in parsed:
            parsed["recommendation"] = "maybe"
        if "summary" not in parsed:
            parsed["summary"] = "Assessment completed."

        logger.info(f"🤖 Structured assessment generated: overall={parsed['overall_score']}, rec={parsed['recommendation']}")
        return json.dumps(parsed)

    except json.JSONDecodeError as e:
        logger.warning(f"Assessment JSON parse failed, returning raw text: {e}")
        return result
    except Exception as e:
        logger.error(f"Assessment generation error: {e}")
        raise
