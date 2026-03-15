"""CV evaluation service using OpenAI LLM."""
import logging
import json
import re
from typing import Dict, Optional
from backend.config import OPENAI_API_KEY

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
        llm_provider: LLM provider to use (ignored, always Gemini)
        llm_model: LLM model to use (defaults to provider default)

    Returns:
        Dictionary with evaluation results
    """
    if llm_model is None:
        llm_model = "gpt-4o"

    logger.info(f"Evaluating CV fit using openai/{llm_model}")

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
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=llm_model,
            messages=[
                {"role": "system", "content": "You are an HR screening assistant. Respond with valid JSON only."},
                {"role": "user", "content": evaluation_prompt}
            ],
            temperature=0.3,
            max_tokens=1000,
        )
        response_text = response.choices[0].message.content

        # Parse JSON response
        evaluation_result = _parse_evaluation_response(response_text)

        logger.info(f"Evaluation complete: {evaluation_result['status']} (score: {evaluation_result.get('score', 'N/A')})")

        return evaluation_result

    except Exception as e:
        logger.error(f"Error evaluating CV: {e}")
        return {
            "status": "rejected",
            "score": 0,
            "skills_match": 0,
            "experience_match": 0,
            "education_match": 0,
            "reasoning": f"Error during evaluation: {str(e)}"
        }


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
        "score": 5,
        "skills_match": 5,
        "experience_match": 5,
        "education_match": 5,
        "reasoning": response_text[:500]
    }
