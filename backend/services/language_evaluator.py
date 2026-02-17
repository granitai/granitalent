"""
Language CV Evaluator - Validates required languages are present in CV.

This module provides DUAL evaluation:
1. Language check - validates required languages are present in CV
2. Job fit check - evaluates overall job fit using original cv_evaluator

Both evaluations are returned separately to display to the user.
"""

import logging
import json
import re
from typing import Dict, Optional

# Import original cv_evaluator for job fit evaluation
from backend.services.cv_evaluator import evaluate_cv_fit as original_evaluate_cv_fit

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def evaluate_cv_fit(
    cv_text: str,
    job_offer_description: str,
    llm_provider: str = None,
    llm_model: str = None,
    required_languages: str = None
) -> Dict[str, any]:
    """
    Perform DUAL evaluation of a candidate's CV.
    
    Two separate evaluations are performed:
    1. Language Check - verifies CV mentions all required languages
    2. Job Fit Check - evaluates overall job fit using LLM
    
    Args:
        cv_text: Parsed text from candidate's CV
        job_offer_description: Full job offer description
        llm_provider: LLM provider for job fit evaluation
        llm_model: LLM model for job fit evaluation
        required_languages: JSON string array of required languages
        
    Returns:
        Dictionary with BOTH evaluation results:
        {
            "status": "approved" | "rejected",  # Overall status
            "language_check": {
                "passed": True/False,
                "languages_found": [...],
                "languages_missing": [...],
                "reasoning": "..."
            },
            "job_fit_check": {
                "status": "approved" | "rejected",
                "score": 0-10,
                "skills_match": 0-10,
                "experience_match": 0-10,
                "education_match": 0-10,
                "reasoning": "..."
            },
            # Legacy fields for backward compatibility
            "score": ...,
            "reasoning": "...",
            "skills_match": ...,
            "experience_match": ...,
            "education_match": ...
        }
    """
    logger.info(f"🌐 Dual CV Evaluator: Running language check + job fit evaluation")
    
    # =========================================================================
    # STEP 1: LANGUAGE CHECK
    # =========================================================================
    language_result = _check_languages(cv_text, job_offer_description, required_languages)
    
    # =========================================================================
    # STEP 2: JOB FIT CHECK (using original cv_evaluator)
    # =========================================================================
    try:
        job_fit_result = original_evaluate_cv_fit(
            cv_text=cv_text,
            job_offer_description=job_offer_description,
            llm_provider=llm_provider,
            llm_model=llm_model
        )
        logger.info(f"📊 Job fit evaluation: {job_fit_result.get('status', 'unknown')}")
    except Exception as e:
        logger.error(f"❌ Error in job fit evaluation: {e}")
        job_fit_result = {
            "status": "error",
            "score": 0,
            "skills_match": 0,
            "experience_match": 0,
            "education_match": 0,
            "reasoning": f"Could not evaluate job fit: {str(e)}"
        }
    
    # =========================================================================
    # STEP 3: COMBINE RESULTS
    # =========================================================================
    # Overall status: ONLY approved if BOTH language check AND job fit passed
    language_passed = language_result["passed"]
    job_fit_passed = job_fit_result.get("status", "rejected") == "approved"
    overall_approved = language_passed and job_fit_passed
    
    # Build combined reasoning
    combined_reasoning = []
    if language_passed:
        combined_reasoning.append(f"✅ Language Check: {language_result['reasoning']}")
    else:
        combined_reasoning.append(f"❌ Language Check: {language_result['reasoning']}")
    
    if job_fit_passed:
        combined_reasoning.append(f"✅ Job Fit: {job_fit_result.get('reasoning', 'Approved')}")
    else:
        combined_reasoning.append(f"❌ Job Fit: {job_fit_result.get('reasoning', 'Rejected')}")
    
    return {
        "status": "approved" if overall_approved else "rejected",
        # Dual evaluation results (shown separately in UI)
        "language_check": language_result,
        "job_fit_check": job_fit_result,
        # Legacy fields for backward compatibility
        "score": job_fit_result.get("score", 0) if overall_approved else 0,
        "skills_match": job_fit_result.get("skills_match", 0),
        "experience_match": job_fit_result.get("experience_match", 0),
        "education_match": job_fit_result.get("education_match", 0),
        "reasoning": " | ".join(combined_reasoning),
        "languages_found": language_result.get("languages_found", []),
        "languages_missing": language_result.get("languages_missing", [])
    }


def _check_languages(cv_text: str, job_offer_description: str, required_languages: str) -> Dict:
    """
    Check if CV contains all required languages.
    
    Returns:
        {
            "passed": True/False,
            "languages_found": [...],
            "languages_missing": [...],
            "reasoning": "..."
        }
    """
    # Parse required languages
    languages_to_check = []
    
    if required_languages:
        try:
            languages_to_check = json.loads(required_languages) if required_languages else []
        except:
            languages_to_check = [l.strip() for l in required_languages.split(",")]
    
    # If no languages specified, try to extract from job description
    if not languages_to_check:
        languages_to_check = _extract_languages_from_description(job_offer_description)
    
    if not languages_to_check:
        return {
            "passed": True,
            "languages_found": [],
            "languages_missing": [],
            "languages_required": [],
            "reasoning": "No specific language requirements specified."
        }
    
    logger.info(f"🌐 Required languages: {languages_to_check}")
    
    # Check which languages are mentioned in CV
    cv_lower = cv_text.lower()
    languages_found = []
    languages_missing = []
    
    for lang in languages_to_check:
        variations = _get_language_variations(lang)
        found = any(v.lower() in cv_lower for v in variations)
        
        if found:
            languages_found.append(lang)
        else:
            languages_missing.append(lang)
    
    if languages_missing:
        logger.warning(f"❌ Languages missing from CV: {languages_missing}")
        return {
            "passed": False,
            "languages_found": languages_found,
            "languages_missing": languages_missing,
            "languages_required": languages_to_check,
            "reasoning": f"Missing required languages: {', '.join(languages_missing)}."
        }
    else:
        logger.info(f"✅ All required languages found: {languages_found}")
        return {
            "passed": True,
            "languages_found": languages_found,
            "languages_missing": [],
            "languages_required": languages_to_check,
            "reasoning": f"All required languages found: {', '.join(languages_found)}."
        }


def _get_language_variations(language: str) -> list:
    """
    Get common variations of a language name.
    
    Args:
        language: Language name (e.g., "French")
        
    Returns:
        List of variations to search for
    """
    variations_map = {
        "english": ["english", "anglais", "inglés", "inglese", "englisch"],
        "french": ["french", "français", "francais", "francés", "franzosisch"],
        "spanish": ["spanish", "español", "espagnol", "spanisch"],
        "german": ["german", "deutsch", "allemand", "alemán", "tedesco"],
        "italian": ["italian", "italiano", "italien"],
        "portuguese": ["portuguese", "português", "portugais"],
        "arabic": ["arabic", "arabe", "arabisch", "عربي"],
        "chinese": ["chinese", "chinois", "mandarin", "cantonese", "中文"],
        "japanese": ["japanese", "japonais", "日本語"],
        "korean": ["korean", "coréen", "한국어"],
        "russian": ["russian", "russe", "русский"],
        "dutch": ["dutch", "néerlandais", "nederlands"],
        "polish": ["polish", "polonais", "polski"],
        "turkish": ["turkish", "turc", "türkçe"],
        "hindi": ["hindi", "हिन्दी"],
    }
    
    lang_lower = language.lower()
    
    # Return mapped variations or just the language itself
    return variations_map.get(lang_lower, [language, lang_lower])


def _extract_languages_from_description(description: str) -> list:
    """
    Try to extract required languages from job description.
    
    Args:
        description: Job offer description
        
    Returns:
        List of languages found in requirements
    """
    if not description:
        return []
    
    desc_lower = description.lower()
    
    # Common language keywords
    common_languages = [
        "English", "French", "Spanish", "German", "Italian", "Portuguese",
        "Arabic", "Chinese", "Mandarin", "Japanese", "Korean", "Russian",
        "Dutch", "Polish", "Turkish", "Hindi"
    ]
    
    found = []
    for lang in common_languages:
        # Look for patterns like "fluent in French" or "French required"
        patterns = [
            rf"\b{lang.lower()}\b.*(?:required|fluent|proficient|native|spoken)",
            rf"(?:speak|speaks|speaking|fluent|proficient|native).*\b{lang.lower()}\b",
            rf"\b{lang.lower()}\b\s+(?:language|speaker)",
        ]
        
        for pattern in patterns:
            if re.search(pattern, desc_lower):
                if lang not in found:
                    found.append(lang)
                break
    
    return found
