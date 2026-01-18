"""OpenAI GPT LLM service."""
import re
import os
import logging
from openai import OpenAI
from typing import List, Dict, Optional
from dotenv import load_dotenv
from backend.config import LLM_PROVIDERS, DEFAULT_LLM_PROVIDER, INTERVIEWER_SYSTEM_PROMPT, build_interviewer_system_prompt

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load OpenAI API key from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("⚠️  WARNING: OPENAI_API_KEY not set in environment variables.")
    logger.warning("   Set OPENAI_API_KEY in your .env file to use GPT models.")
    logger.warning("   Get your API key from: https://platform.openai.com/api-keys")

# Initialize OpenAI client (only if API key is available)
if OPENAI_API_KEY:
    client = OpenAI(
        api_key=OPENAI_API_KEY,
    )
else:
    client = None

# Get default model
DEFAULT_LLM_MODEL = LLM_PROVIDERS.get("gpt", {}).get("default_model", "gpt-4o-mini")


def normalize_model_name(model_id: str) -> str:
    """
    Normalize model name by removing 'openai/' prefix if present.
    This allows backward compatibility with old model names.
    """
    if model_id.startswith("openai/"):
        return model_id.replace("openai/", "", 1)
    return model_id


def clean_response(text: str) -> str:
    """
    Clean the LLM response by removing role prefixes.
    """
    # Remove "Interviewer:" or "Interviewer :" prefix if present
    text = re.sub(r'^(Interviewer\s*:\s*)', '', text, flags=re.IGNORECASE)
    return text.strip()


def generate_response(
    conversation_history: List[Dict[str, str]], 
    user_message: str,
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None
) -> str:
    """
    Generate a response using OpenAI GPT LLM.
    
    Args:
        conversation_history: List of previous messages in format [{"role": "user"/"assistant", "content": "..."}]
        user_message: The current user message
        model_id: The GPT model to use (defaults to config default)
        interview_context: Optional dict with job_title, job_offer_description, candidate_cv_text
    
    Returns:
        The generated response text
    """
    if model_id is None:
        model_id = DEFAULT_LLM_MODEL
    
    logger.info(f"🤖 LLM: Using model '{model_id}'")
    logger.info(f"🤖 LLM: User message: '{user_message[:50]}...'" if len(user_message) > 50 else f"🤖 LLM: User message: '{user_message}'")
    
    # Check for potential jailbreak attempts
    jailbreak_keywords = [
        "ignore previous instructions", "forget you are", "pretend you are", "act as if",
        "you are now", "roleplay as", "you're not", "stop being", "break character",
        "system prompt", "developer mode", "jailbreak", "bypass", "override"
    ]
    user_lower = user_message.lower()
    is_potential_jailbreak = any(keyword in user_lower for keyword in jailbreak_keywords)
    
    # Build context-aware system prompt
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
            questions_in_current_language=interview_context.get("questions_in_current_language")
        )
        logger.info(f"🤖 LLM: Using context-aware prompt for position: {interview_context.get('job_title', 'Unknown')}")
        if interview_context.get("time_remaining_minutes") is not None:
            total = interview_context.get('total_interview_minutes', 20)
            remaining = interview_context.get('time_remaining_minutes')
            logger.info(f"⏱️ Time: {remaining:.1f}/{total:.0f} min remaining ({remaining/total*100:.0f}%)")
        
        # Log language context
        req_langs = interview_context.get("required_languages_list", [])
        if req_langs and len(req_langs) > 1:
            current_lang = interview_context.get("current_language", "Unknown")
            tested = interview_context.get("tested_languages", [])
            q_count = interview_context.get("questions_in_current_language", 0)
            untested = [l for l in req_langs if l not in tested]
            logger.info(f"🌐 Language: {current_lang} ({q_count} questions), Untested: {untested}")
    else:
        system_prompt = INTERVIEWER_SYSTEM_PROMPT
    
    # Add time awareness to system content
    time_awareness = ""
    if interview_context:
        time_remaining = interview_context.get("time_remaining_minutes")
        total_time = interview_context.get("total_interview_minutes")
        
        if time_remaining is not None:
            if time_remaining <= 0:
                time_awareness = f"\n\n⏱️ **TIME IS UP!** CONCLUDE NOW. Say: 'Our time is up. Thank you for your time! HR will review your application and contact you soon.'"
            elif time_remaining <= 1:
                time_awareness = f"\n\n⏱️ **{time_remaining:.0f} MIN LEFT - CONCLUDE NOW!**\nSay: 'We're out of time. Thank you! HR will review your application and contact you soon.'"
            elif time_remaining <= 2:
                time_awareness = f"\n\n⏱️ **{time_remaining:.1f} MIN LEFT - START CONCLUDING**\nSay: 'We're running short on time.' Ask if they have questions, then conclude with: 'Thank you! HR will contact you soon.'"
            elif time_remaining <= 3:
                time_awareness = f"\n\n⏱️ **{time_remaining:.1f} MIN LEFT**\nYou have time for 1-2 more questions. Don't rush to conclude yet."
    
    # Get current language from context
    current_language = interview_context.get("current_language") if interview_context else None
    interview_start_language = interview_context.get("interview_start_language") if interview_context else None
    language_to_use = current_language or interview_start_language or "English"
    
    # Log language context for debugging
    if interview_context:
        untested = interview_context.get("untested_languages", [])
        q_count = interview_context.get("questions_in_current_language", 0)
        if untested:
            logger.info(f"🌐 Language context: Speaking {language_to_use} ({q_count} questions). Still need to test: {untested}")
    
    # Build language validation instruction if there are untested languages
    language_validation = ""
    if interview_context:
        untested = interview_context.get("untested_languages", [])
        if untested:
            language_validation = f"""

LANGUAGE TESTING - CRITICAL:
- Languages still needing evaluation: {', '.join(untested)}
- When switching to test a new language:
  1. Be EXPLICIT: "Now let's evaluate your [Language]. Please answer IN [LANGUAGE]."
  2. Ask your question IN that target language (not in English)
  3. If they respond in the wrong language, say: "I notice you responded in [wrong language]. For this evaluation, I need your answer IN [target language]. Please try again."
  4. Do NOT accept wrong-language responses as valid for that language test
- NEVER give performance feedback. When concluding say: "Thank you! HR will review your application and contact you soon."
"""
    
    # Build messages for OpenAI API
    system_content = f"""{system_prompt}{time_awareness}{language_validation}

Respond in {language_to_use} (or switch to another required language if you decide it's appropriate).

RULES:
- No 'Interviewer:' prefix. Stay in character.
- ONE concise response only.
- Be friendly and ask smart questions.
- When switching languages, be EXPLICIT: "Please answer IN [Language]" and ask in that language.
- If candidate responds in wrong language, ask them to respond again in the correct language.
- NEVER give performance feedback or hints about how well they did."""
    
    messages = [
        {
            "role": "system",
            "content": system_content
        }
    ]
    
    # Check for language switch requests
    language_switch_keywords = [
        "switch to", "switch language", "speak in", "parler en", "parlez", "continue in",
        "now in", "in english", "in french", "en français", "en anglais", "en arabe",
        "can we speak", "peut-on parler", "let's speak", "parlons", "change to",
        "change language", "changer de langue", "autre langue"
    ]
    user_lower = user_message.lower()
    is_language_switch_request = any(keyword in user_lower for keyword in language_switch_keywords)
    
    # Detect which language they want to switch to
    target_language = None
    if is_language_switch_request:
        if any(word in user_lower for word in ["french", "français", "francais", "français"]):
            target_language = "French"
        elif any(word in user_lower for word in ["english", "anglais"]):
            target_language = "English"
        elif any(word in user_lower for word in ["arabic", "arabe", "عربي"]):
            target_language = "Arabic"
        elif any(word in user_lower for word in ["spanish", "espagnol", "español"]):
            target_language = "Spanish"
        elif any(word in user_lower for word in ["german", "allemand", "deutsch"]):
            target_language = "German"
        
        if target_language:
            logger.info(f"🌐 Language switch request detected: Switching to {target_language}")
        else:
            logger.info(f"🌐 Language switch request detected but target language unclear")
    
    # Add conversation history (convert assistant role to OpenAI format)
    for msg in conversation_history:
        role = "assistant" if msg["role"] == "assistant" else "user"
        messages.append({
            "role": role,
            "content": msg["content"]
        })
    
    # Add explicit language switch instruction if detected (candidate request)
    if is_language_switch_request and target_language:
        messages.append({
            "role": "system",
            "content": f"The candidate asked to switch to {target_language}. Please continue the interview in {target_language}."
        })
    
    # Add user message
    user_content = user_message
    if is_language_switch_request and target_language:
        user_content = f"{user_message}\n\n[Continue in {target_language}]"
    
    messages.append({
        "role": "user",
        "content": user_content
    })
    
    # Handle jailbreak attempts
    if is_potential_jailbreak:
        logger.warning(f"⚠️ Potential jailbreak attempt detected: {user_message[:50]}...")
        # Update the user message with redirect instruction (already added above)
        messages[-1]["content"] = f"{user_message}\n\n[Note: The candidate seems to be trying to change the topic. As a professional interviewer, politely acknowledge this but redirect back to interview questions. Stay friendly and warm.]"
    
    # Normalize model name (remove 'openai/' prefix if present)
    normalized_model = normalize_model_name(model_id)
    
    # Generate response using OpenAI API
    if not client:
        raise ValueError("OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.")
    
    try:
        # Follow OpenAI best practices: use proper parameters to prevent multiple responses
        response = client.chat.completions.create(
            model=normalized_model,
            messages=messages,
            temperature=0.7,
            max_tokens=300,  # Reduced to encourage concise responses
            top_p=0.9,  # Nucleus sampling for better control
            frequency_penalty=0.3,  # Reduce repetition
            presence_penalty=0.3  # Encourage new topics
        )
        
        # Extract response text
        response_text = response.choices[0].message.content
        
        # Clean the response
        cleaned = clean_response(response_text)
        
        if is_potential_jailbreak:
            logger.info(f"🛡️ Jailbreak protection: Redirected to interview topic")
        
        logger.info(f"🤖 LLM: Generated response: '{cleaned[:50]}...'" if len(cleaned) > 50 else f"🤖 LLM: Generated response: '{cleaned}'")
        
        return cleaned
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "invalid_api_key" in error_msg.lower():
            logger.error(f"❌ Invalid OpenAI API key. Please check your OPENAI_API_KEY in your .env file.")
            logger.error(f"   Get your API key from: https://platform.openai.com/api-keys")
            raise ValueError("Invalid OpenAI API key. Please check your OPENAI_API_KEY in your .env file.")
        logger.error(f"Error generating GPT response: {e}")
        raise


def generate_audio_check_message(model_id: Optional[str] = None, language: Optional[str] = None) -> str:
    """
    Generate the initial audio check message.
    
    Args:
        model_id: The GPT model to use (defaults to config default)
        language: The language to use (e.g., "French", "English", "Arabic"). If None, defaults to English.
    
    Returns:
        Audio check message text
    """
    if model_id is None:
        model_id = DEFAULT_LLM_MODEL
    
    lang_instruction = f"Respond in {language}." if language else "Respond in English."
    
    logger.info(f"🤖 LLM: Generating audio check message with model '{model_id}' in language '{language or 'English'}'")
    
    messages = [
        {
            "role": "system",
            "content": "You are a friendly AI interviewer. Be warm, brief, and conversational."
        },
        {
            "role": "user",
            "content": f"{lang_instruction}\n\nBefore starting the interview, you want to make sure everything is working properly. Say a brief, friendly message to check if the candidate can hear you. Something like 'Hi, can you hear me?' or 'Hello, do you hear me okay?' but in the specified language. Keep it very brief (1 sentence), warm, and friendly. Respond only with what you would say, without any prefix."
        }
    ]
    
    # Normalize model name
    normalized_model = normalize_model_name(model_id) if model_id else DEFAULT_LLM_MODEL
    
    if not client:
        raise ValueError("OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.")
    
    try:
        response = client.chat.completions.create(
            model=normalized_model,
            messages=messages,
            temperature=0.7,
            max_tokens=50
        )
        return clean_response(response.choices[0].message.content)
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "invalid_api_key" in error_msg.lower():
            logger.error(f"❌ Invalid OpenAI API key. Please check your OPENAI_API_KEY in your .env file.")
            logger.error(f"   Get your API key from: https://platform.openai.com/api-keys")
            raise ValueError("Invalid OpenAI API key. Please check your OPENAI_API_KEY in your .env file.")
        logger.error(f"Error generating GPT audio check: {e}")
        raise


def generate_name_request_message(model_id: Optional[str] = None, language: Optional[str] = None) -> str:
    """
    Generate the name request message.
    
    Args:
        model_id: The GPT model to use (defaults to config default)
        language: The language to use (e.g., "French", "English", "Arabic"). If None, defaults to English.
    
    Returns:
        Name request message text
    """
    if model_id is None:
        model_id = DEFAULT_LLM_MODEL
    
    lang_instruction = f"Respond in {language}." if language else "Respond in English."
    
    logger.info(f"🤖 LLM: Generating name request message with model '{model_id}' in language '{language or 'English'}'")
    
    messages = [
        {
            "role": "system",
            "content": "You are a friendly AI interviewer. Be warm, brief, and conversational."
        },
        {
            "role": "user",
            "content": f"{lang_instruction}\n\nYou've confirmed the candidate can hear you. Now you want to get their name to make sure the audio and speech recognition are working correctly. Ask the candidate to tell you their name and how it's spelled. Be warm and friendly. Something like 'Great! Can you please tell me your name and how it's spelled?' or 'Perfect! Could you tell me your name and spell it for me?' but in the specified language. Keep it brief (1-2 sentences), warm, and friendly. Respond only with what you would say, without any prefix."
        }
    ]
    
    # Normalize model name
    normalized_model = normalize_model_name(model_id) if model_id else DEFAULT_LLM_MODEL
    
    if not client:
        raise ValueError("OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.")
    
    try:
        response = client.chat.completions.create(
            model=normalized_model,
            messages=messages,
            temperature=0.7,
            max_tokens=80
        )
        return clean_response(response.choices[0].message.content)
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "invalid_api_key" in error_msg.lower():
            logger.error(f"❌ Invalid OpenAI API key. Please check your OPENAI_API_KEY in your .env file.")
            logger.error(f"   Get your API key from: https://platform.openai.com/api-keys")
            raise ValueError("Invalid OpenAI API key. Please check your OPENAI_API_KEY in your .env file.")
        logger.error(f"Error generating GPT name request: {e}")
        raise


def generate_opening_greeting(
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None,
    candidate_name: Optional[str] = None
) -> str:
    """
    Generate an opening greeting for the interview.
    The AI interviewer starts the conversation.
    
    Args:
        model_id: The GPT model to use (defaults to config default)
        interview_context: Optional dict with job_title, job_offer_description, candidate_cv_text
    
    Returns:
        Opening greeting text
    """
    if model_id is None:
        model_id = DEFAULT_LLM_MODEL
    
    logger.info(f"🤖 LLM: Generating greeting with model '{model_id}'")
    
    # Build context-aware system prompt and greeting instruction
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
            questions_in_current_language=interview_context.get("questions_in_current_language")
        )
        job_title = interview_context.get("job_title", "this position")
        logger.info(f"🤖 LLM: Generating context-aware greeting for position: {job_title}")
        
        # Include candidate name if available
        name_mention = f"Hi {candidate_name}," if candidate_name else "Hi,"
        
        # Get interview start language for greeting
        interview_start_language = interview_context.get("interview_start_language")
        lang_instruction = f"Respond in {interview_start_language}." if interview_start_language else "Respond in English."
        
        greeting_instruction = f"""{lang_instruction}

Start the actual interview by:
1. Greeting the candidate warmly using their name ({name_mention if candidate_name else "Hi,"})
2. Mentioning the position they're interviewing for ({job_title})
3. Briefly acknowledging you've reviewed their CV
4. Asking them to introduce themselves and tell you what interests them about this role

Keep it brief, friendly, and professional. Maximum 3-4 sentences.
Respond in {interview_start_language if interview_start_language else 'English'}. No prefix like 'Interviewer:'."""
    else:
        name_mention = f"Hi {candidate_name}," if candidate_name else "Hi,"
        system_prompt = INTERVIEWER_SYSTEM_PROMPT
        greeting_instruction = f"Start the interview by greeting the candidate warmly{f' using their name ({name_mention})' if candidate_name else ''} and asking them to introduce themselves. Keep it brief, friendly, and professional. Maximum 2-3 sentences. Respond only with what you would say, without any prefix like 'Interviewer:'."
    
    messages = [
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user",
            "content": greeting_instruction
        }
    ]
    
    # Normalize model name
    normalized_model = normalize_model_name(model_id) if model_id else DEFAULT_LLM_MODEL
    
    if not client:
        raise ValueError("OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.")
    
    try:
        response = client.chat.completions.create(
            model=normalized_model,
            messages=messages,
            temperature=0.7,
            max_tokens=200
        )
        
        response_text = response.choices[0].message.content
        return clean_response(response_text)
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "invalid_api_key" in error_msg.lower():
            logger.error(f"❌ Invalid OpenAI API key. Please check your OPENAI_API_KEY in your .env file.")
            logger.error(f"   Get your API key from: https://platform.openai.com/api-keys")
            raise ValueError("Invalid OpenAI API key. Please check your OPENAI_API_KEY in your .env file.")
        logger.error(f"Error generating GPT greeting: {e}")
        raise


def generate_assessment(
    conversation_history: List[Dict[str, str]],
    model_id: Optional[str] = None,
    interview_context: Optional[Dict[str, str]] = None
) -> str:
    """
    Generate an assessment of the interview and candidate.
    Only evaluates if there's meaningful interview conversation.
    
    Args:
        conversation_history: The full conversation history
        model_id: The GPT model to use (defaults to config default)
        interview_context: Optional dict with job_title, job_offer_description, candidate_cv_text
    
    Returns:
        Assessment text, or message indicating no meaningful conversation
    """
    if model_id is None:
        model_id = DEFAULT_LLM_MODEL
    
    logger.info(f"🤖 LLM: Generating assessment with model '{model_id}'")
    
    # Filter out pre-check messages (audio check, name check)
    precheck_keywords = ["can you hear me", "do you hear me", "tell me your name", "how it's spelled"]
    
    # Count meaningful candidate responses (excluding pre-check)
    meaningful_candidate_responses = []
    meaningful_interviewer_questions = []
    
    for msg in conversation_history:
        content_lower = msg["content"].lower()
        is_precheck = any(keyword in content_lower for keyword in precheck_keywords)
        
        if msg["role"] == "user" and not is_precheck:
            # Candidate response - check if it's meaningful (not just "yes", "ok", etc.)
            if len(msg["content"].strip()) > 10:  # More than just short acknowledgments
                meaningful_candidate_responses.append(msg["content"])
        elif msg["role"] == "assistant" and not is_precheck:
            # Interviewer question - check if it's an actual interview question
            if len(msg["content"].strip()) > 20:  # More than just greetings
                meaningful_interviewer_questions.append(msg["content"])
    
    # Check if there's meaningful conversation
    has_meaningful_conversation = (
        len(meaningful_candidate_responses) >= 2 and 
        len(meaningful_interviewer_questions) >= 2
    )
    
    if not has_meaningful_conversation:
        logger.warning("⚠️ No meaningful conversation detected - candidate may not have spoken or answered questions")
        return """**Interview Assessment**

**Status**: No meaningful conversation occurred

**Summary**: 
The interview did not contain sufficient meaningful conversation to provide an evaluation. This could be because:
- The candidate did not respond to interview questions
- The candidate only provided very brief or minimal responses
- The conversation was limited to pre-interview checks (audio/name verification)
- Technical issues may have prevented proper communication

**Recommendation**: 
A proper evaluation cannot be provided as there was insufficient interview content. Please ensure the candidate is able to participate fully in the interview before generating an assessment."""
    
    # Build conversation transcript (filter out very short pre-check responses)
    transcript = []
    for msg in conversation_history:
        content_lower = msg["content"].lower()
        is_precheck = any(keyword in content_lower for keyword in precheck_keywords)
        
        # Skip very short pre-check responses
        if is_precheck and len(msg["content"].strip()) < 15:
            continue
            
        role = "Interviewer" if msg["role"] == "assistant" else "Candidate"
        transcript.append(f"{role}: {msg['content']}")
    
    transcript_text = "\n".join(transcript)
    
    # Build context section if available
    context_section = ""
    if interview_context:
        job_title = interview_context.get("job_title", "Unknown Position")
        job_description = interview_context.get("job_offer_description", "")
        cv_text = interview_context.get("candidate_cv_text", "")
        
        context_section = f"""
=== JOB POSITION ===
{job_title}

{job_description}

=== CANDIDATE CV ===
{cv_text[:2000]}{"..." if len(cv_text) > 2000 else ""}

"""
        logger.info(f"🤖 LLM: Generating context-aware assessment for position: {job_title}")
    
    # Check if language evaluation is needed - ONLY for languages actually tested
    language_section = ""
    required_languages = interview_context.get("required_languages") if interview_context else None
    tested_languages = interview_context.get("tested_languages", []) if interview_context else []
    
    if required_languages:
        try:
            import json
            all_languages = json.loads(required_languages) if required_languages else []
            
            # Only evaluate languages that were actually tested
            if tested_languages and len(tested_languages) > 0:
                tested_list = list(tested_languages) if isinstance(tested_languages, set) else tested_languages
                untested = [lang for lang in all_languages if lang not in tested_list]
                
                logger.info(f"🌐 Assessment: Tested languages: {tested_list}, Untested: {untested}")
                
                language_section = f"""
10. **Linguistic Capacity** - CRITICAL: ONLY evaluate languages that were ACTUALLY TESTED in the transcript.
    
    Languages that WERE tested during this interview: {', '.join(tested_list)}
    Languages that were NOT tested (DO NOT SCORE THESE): {', '.join(untested) if untested else 'None'}
    
    **IMPORTANT**: 
    - ONLY provide scores for languages listed as "WERE tested" above
    - For untested languages, write "NOT TESTED - No score can be provided as this language was not evaluated during the interview"
    - Do NOT invent or fabricate scores for languages that were not tested
    
    For each TESTED language only, provide a score (0-10) and brief assessment covering:
    - Fluency and naturalness
    - Vocabulary range and accuracy
    - Grammar and syntax
    - Ability to discuss technical topics
"""
            else:
                # No languages were explicitly tested
                language_section = f"""
10. **Linguistic Capacity** - Note: Required languages are {', '.join(all_languages)}, but language testing may not have occurred.
    Only score languages if there is clear evidence in the transcript of the candidate speaking in that language.
    If a language was not tested, write "NOT TESTED - cannot evaluate".
"""
        except Exception as e:
            logger.warning(f"⚠️ Error parsing language requirements: {e}")
            pass
    
    assessment_prompt = f"""You are an expert interview assessor. Based on the following interview information, provide a comprehensive assessment.

{context_section}=== INTERVIEW TRANSCRIPT ===
{transcript_text}

CRITICAL INSTRUCTIONS:
1. **ONLY USE WHAT IS IN THE TRANSCRIPT ABOVE** - Do NOT invent, assume, or make up any candidate responses that are not explicitly shown in the transcript.
2. **If the candidate did not answer a question, state that clearly** - Do NOT pretend they answered it.
3. **If the candidate gave minimal responses, reflect that in your scores** - Low engagement should result in lower scores, not made-up positive evaluations.
4. **Only provide an evaluation if there is meaningful interview conversation** - If the candidate barely spoke, gave only one-word answers, or didn't engage, state that clearly instead of giving scores.

Please provide a detailed assessment in the following format. For each evaluation axis, provide:
1. A score from 0-10
2. A brief explanation of the score that references SPECIFIC responses from the transcript above

**Evaluation Axes:**
1. **Technical Skills** (0-10) - How well did the candidate demonstrate technical knowledge relevant to the position? ONLY evaluate based on what they actually said in the transcript.
2. **Job Fit** (0-10) - How well does the candidate match the specific requirements of this position? ONLY evaluate based on their actual responses.
3. **Communication Skills** (0-10) - How clearly did they express their ideas? Base this ONLY on their actual spoken words in the transcript.
4. **Problem-Solving Ability** (0-10) - How did they approach questions? If they didn't answer problem-solving questions, score this low and state why.
5. **CV Consistency** (0-10) - Did their interview responses align with their CV claims? ONLY compare what they actually said to their CV.
{language_section}
**Additional Sections:**
- **Areas of Strength** - What did the candidate do well? ONLY mention things they actually demonstrated in the transcript.
- **Areas for Improvement** - What could they work on? Be honest about what was missing or insufficient.
- **Hiring Recommendation** - Would you recommend this candidate for THIS specific position? Why or why not? Base this ONLY on their actual performance in the transcript.

At the end, provide:
- **Overall Score** (0-10) - Calculate the mean of all axis scores
- **Score Calculation** - Show how the overall score was calculated (mean of all axis scores)

REMEMBER: Every claim you make must be supported by actual text from the transcript above. If something wasn't discussed, don't pretend it was. If the candidate didn't answer questions, reflect that honestly in your assessment."""
    
    messages = [
        {
            "role": "system",
            "content": "You are an expert interview assessor. Provide detailed, constructive feedback based on interview transcripts and job requirements."
        },
        {
            "role": "user",
            "content": assessment_prompt
        }
    ]
    
    # Normalize model name
    normalized_model = normalize_model_name(model_id) if model_id else DEFAULT_LLM_MODEL
    
    if not client:
        raise ValueError("OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.")
    
    try:
        response = client.chat.completions.create(
            model=normalized_model,
            messages=messages,
            temperature=0.7,
            max_tokens=2000
        )
        
        return response.choices[0].message.content.strip()
    except Exception as e:
        error_msg = str(e)
        if "401" in error_msg or "invalid_api_key" in error_msg.lower():
            logger.error(f"❌ Invalid OpenAI API key. Please check your OPENAI_API_KEY in your .env file.")
            logger.error(f"   Get your API key from: https://platform.openai.com/api-keys")
            raise ValueError("Invalid OpenAI API key. Please check your OPENAI_API_KEY in your .env file.")
        logger.error(f"Error generating GPT assessment: {e}")
        raise
