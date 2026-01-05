"""CV evaluation service using LLM."""
import logging
import json
import re
from typing import Dict, Optional
from backend.config import LLM_PROVIDERS, DEFAULT_LLM_PROVIDER
from backend.services.gemini_llm import generate_response as gemini_generate
from backend.services.gpt_llm import generate_response as gpt_generate

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def evaluate_cv_fit(
    cv_text: str,
    job_offer_description: str,
    llm_provider: str = None,
    llm_model: str = None
) -> Dict[str, any]:
    """
    Evaluate if a candidate's CV matches the job offer requirements.
    
    Args:
        cv_text: Parsed text from candidate's CV
        job_offer_description: Full job offer description
        llm_provider: LLM provider to use (defaults to config default)
        llm_model: LLM model to use (defaults to provider default)
        
    Returns:
        Dictionary with evaluation results:
        {
            "status": "approved" | "rejected",
            "score": 0-10,
            "reasoning": "Detailed explanation",
            "skills_match": 0-10,
            "experience_match": 0-10,
            "education_match": 0-10
        }
    """
    if llm_provider is None:
        llm_provider = DEFAULT_LLM_PROVIDER
    
    if llm_model is None:
        llm_model = LLM_PROVIDERS[llm_provider]["default_model"]
    
    logger.info(f"🔍 Evaluating CV fit using {llm_provider}/{llm_model}")
    
    # Create evaluation prompt
    evaluation_prompt = f"""You are an HR screening assistant. Evaluate if the candidate's CV matches the job requirements.

JOB OFFER:
{job_offer_description}

CANDIDATE CV:
{cv_text}

Please evaluate the candidate's fit for this position. Provide your assessment in the following JSON format:
{{
    "status": "approved" or "rejected",
    "score": 0-10 (overall fit score),
    "skills_match": 0-10,
    "experience_match": 0-10,
    "education_match": 0-10,
    "reasoning": "Detailed explanation of your assessment. If rejected, provide specific reasons (e.g., 'Candidate is a software engineer but position requires data analyst skills')."
}}

Be thorough and specific. If the candidate clearly doesn't match (e.g., wrong field, missing critical skills), set status to "rejected" and explain why. If there's reasonable fit, set status to "approved"."""

    try:
        # Use appropriate LLM based on provider
        if llm_provider == "gemini":
            response_text = _evaluate_with_gemini(evaluation_prompt, llm_model)
        elif llm_provider == "gpt":
            response_text = _evaluate_with_gpt(evaluation_prompt, llm_model)
        else:
            raise ValueError(f"Unknown LLM provider: {llm_provider}")
        
        # Parse JSON response
        evaluation_result = _parse_evaluation_response(response_text)
        
        logger.info(f"✅ Evaluation complete: {evaluation_result['status']} (score: {evaluation_result.get('score', 'N/A')})")
        
        return evaluation_result
        
    except Exception as e:
        logger.error(f"❌ Error evaluating CV: {e}")
        # Return a safe default rejection
        return {
            "status": "rejected",
            "score": 0,
            "skills_match": 0,
            "experience_match": 0,
            "education_match": 0,
            "reasoning": f"Error during evaluation: {str(e)}"
        }


def _evaluate_with_gemini(prompt: str, model_id: str) -> str:
    """Evaluate using Gemini LLM."""
    import google.generativeai as genai
    from backend.config import GOOGLE_API_KEY
    
    genai.configure(api_key=GOOGLE_API_KEY)
    model = genai.GenerativeModel(model_id)
    response = model.generate_content(prompt)
    return response.text


def _evaluate_with_gpt(prompt: str, model_id: str) -> str:
    """Evaluate using GPT LLM."""
    from openai import OpenAI
    
    # Get OpenRouter API key from gpt_llm module
    import backend.services.gpt_llm as gpt_module
    openrouter_key = getattr(gpt_module, 'OPENROUTER_API_KEY', None)
    
    if not openrouter_key:
        raise ValueError("OpenRouter API key not found. Please configure it in gpt_llm.py")
    
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=openrouter_key,
    )
    
    response = client.chat.completions.create(
        model=model_id,
        messages=[
            {
                "role": "system",
                "content": "You are an HR screening assistant. Always respond with valid JSON."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.3,
        max_tokens=1000
    )
    
    return response.choices[0].message.content


def _parse_evaluation_response(response_text: str) -> Dict:
    """Parse LLM response and extract evaluation data."""
    # Try to extract JSON from response
    json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group())
            # Validate and set defaults
            return {
                "status": result.get("status", "rejected").lower(),
                "score": int(result.get("score", 0)),
                "skills_match": int(result.get("skills_match", 0)),
                "experience_match": int(result.get("experience_match", 0)),
                "education_match": int(result.get("education_match", 0)),
                "reasoning": result.get("reasoning", "No reasoning provided")
            }
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from response")
    
    # Fallback: try to extract status and reasoning from text
    status = "rejected"
    if "approved" in response_text.lower() or "approve" in response_text.lower():
        status = "approved"
    elif "rejected" in response_text.lower() or "reject" in response_text.lower():
        status = "rejected"
    
    return {
        "status": status,
        "score": 5,  # Default score
        "skills_match": 5,
        "experience_match": 5,
        "education_match": 5,
        "reasoning": response_text[:500]  # Use first 500 chars as reasoning
    }
