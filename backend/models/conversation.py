"""Conversation state management for the interview."""
from typing import List, Dict, Optional, Set
from datetime import datetime
import json


class ConversationManager:
    """Manages conversation history and state."""
    
    # Pre-check phase states
    PHASE_AUDIO_CHECK = "audio_check"  # Checking if candidate can hear
    PHASE_NAME_CHECK = "name_check"    # Getting candidate's name
    PHASE_INTERVIEW = "interview"      # Actual interview started
    
    def __init__(
        self,
        job_offer_description: Optional[str] = None,
        candidate_cv_text: Optional[str] = None,
        job_title: Optional[str] = None,
        required_languages: Optional[str] = None,
        interview_start_language: Optional[str] = None,
        custom_questions: Optional[str] = None,
        evaluation_weights: Optional[str] = None
    ):
        """
        Initialize a new conversation.
        
        Args:
            job_offer_description: Full job offer description for context
            candidate_cv_text: Parsed text from candidate's CV
            job_title: Title of the job position
            required_languages: JSON string array of required languages
            interview_start_language: Language to start the interview with
            custom_questions: JSON string array of custom questions from recruiter
            evaluation_weights: JSON string object of evaluation weights
        """
        self.history: List[Dict[str, str]] = []
        self.created_at = datetime.now()
        self.job_offer_description = job_offer_description
        self.candidate_cv_text = candidate_cv_text
        self.job_title = job_title
        self.required_languages = required_languages
        self.interview_start_language = interview_start_language
        self.custom_questions = custom_questions
        self.evaluation_weights = evaluation_weights
        self.phase = self.PHASE_AUDIO_CHECK  # Start with audio check
        self.candidate_name: Optional[str] = None
        self.candidate_name_spelling: Optional[str] = None
        self.cv_candidate_name: Optional[str] = None  # Name from CV (source of truth)
        self.confirmed_candidate_name: Optional[str] = None  # Confirmed name that should never change
        self.covered_topics: Set[str] = set()  # Track topics/questions covered
        self.tested_languages: Set[str] = set()  # Track languages that have been tested
        self.current_language: Optional[str] = interview_start_language  # Current interview language
        self.questions_in_current_language: int = 0  # Count questions asked in current language
        
        # Mark the starting language as tested immediately
        if interview_start_language:
            self.tested_languages.add(interview_start_language)
    
    def get_interview_context(self, time_remaining_minutes: Optional[float] = None, total_interview_minutes: Optional[float] = None) -> Dict[str, Optional[str]]:
        """Get the interview context (job offer and candidate profile)."""
        required_list = self.get_required_languages_list()
        untested = [lang for lang in required_list if lang not in self.tested_languages]
        
        # Provide information for AI to make intelligent decisions - no forcing
        context = {
            "job_title": self.job_title,
            "job_offer_description": self.job_offer_description,
            "candidate_cv_text": self.candidate_cv_text,
            "required_languages": self.required_languages,
            "interview_start_language": self.interview_start_language,
            "confirmed_candidate_name": self.confirmed_candidate_name,
            "covered_topics": list(self.covered_topics),
            "tested_languages": list(self.tested_languages),
            "current_language": self.current_language,
            "required_languages_list": required_list,
            "questions_in_current_language": self.questions_in_current_language,
            "untested_languages": untested,
            "languages_remaining_count": len(untested),
            "custom_questions": self.custom_questions,
            "evaluation_weights": self.evaluation_weights,
        }
        if time_remaining_minutes is not None:
            context["time_remaining_minutes"] = time_remaining_minutes
        if total_interview_minutes is not None:
            context["total_interview_minutes"] = total_interview_minutes
        return context
    
    def get_current_phase(self) -> str:
        """Get the current conversation phase."""
        return self.phase
    
    def set_phase(self, phase: str):
        """Set the conversation phase."""
        self.phase = phase
    
    def set_cv_candidate_name(self, name: str):
        """Store the candidate's name from CV (source of truth)."""
        self.cv_candidate_name = name
        # If we already have a CV name, use it as the confirmed name
        if not self.confirmed_candidate_name:
            self.confirmed_candidate_name = name
    
    def set_candidate_name(self, name: str, spelling: Optional[str] = None):
        """Store the candidate's name and spelling from spoken verification."""
        self.candidate_name = name
        self.candidate_name_spelling = spelling
        # Once confirmed during name check, use CV name as the confirmed name (source of truth)
        # The spoken name is just for verification - CV name is always correct
        if self.phase == self.PHASE_NAME_CHECK:
            # Use CV name if available, otherwise use spoken name
            if self.cv_candidate_name:
                self.confirmed_candidate_name = self.cv_candidate_name
            else:
                self.confirmed_candidate_name = name
    
    def get_candidate_name(self) -> Optional[str]:
        """Get the candidate's name. Always returns confirmed name if available."""
        return self.confirmed_candidate_name or self.candidate_name
    
    def get_confirmed_name(self) -> Optional[str]:
        """Get the confirmed candidate name (never changes after confirmation)."""
        return self.confirmed_candidate_name
    
    def add_covered_topic(self, topic: str):
        """Mark a topic as covered."""
        self.covered_topics.add(topic.lower())
    
    def get_covered_topics(self) -> Set[str]:
        """Get set of covered topics."""
        return self.covered_topics.copy()
    
    def add_tested_language(self, language: str):
        """Mark a language as tested."""
        self.tested_languages.add(language)
    
    def get_tested_languages(self) -> Set[str]:
        """Get set of tested languages."""
        return self.tested_languages.copy()
    
    def set_current_language(self, language: str):
        """Set the current interview language."""
        if self.current_language != language:
            # Language changed - reset question count
            self.questions_in_current_language = 0
        self.current_language = language
        self.add_tested_language(language)
    
    def increment_question_count(self):
        """Increment the count of questions asked in current language."""
        self.questions_in_current_language += 1
    
    def get_questions_in_current_language(self) -> int:
        """Get count of questions asked in current language."""
        return self.questions_in_current_language
    
    def get_current_language(self) -> Optional[str]:
        """Get the current interview language."""
        return self.current_language
    
    def get_required_languages_list(self) -> List[str]:
        """Get list of required languages."""
        if not self.required_languages:
            return []
        try:
            return json.loads(self.required_languages) if isinstance(self.required_languages, str) else self.required_languages
        except:
            return []
    
    def add_message(self, role: str, text: str):
        """
        Add a message to the conversation history.
        
        Args:
            role: Either 'user' or 'interviewer'
            text: The message content
        """
        self.history.append({
            "role": role,
            "text": text,
            "timestamp": datetime.now().isoformat()
        })
    
    def get_history(self) -> List[Dict[str, str]]:
        """Get the full conversation history."""
        return self.history.copy()
    
    def get_history_for_llm(self) -> List[Dict[str, str]]:
        """
        Get conversation history formatted for LLM API.
        Returns list of dicts with 'role' and 'content' keys.
        """
        formatted_history = []
        for msg in self.history:
            # Map 'interviewer' to 'assistant' for LLM
            role = "assistant" if msg["role"] == "interviewer" else "user"
            formatted_history.append({
                "role": role,
                "content": msg["text"]
            })
        return formatted_history
    
    def reset(self):
        """Reset the conversation history."""
        self.history = []
        self.created_at = datetime.now()
