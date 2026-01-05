"""Conversation state management for the interview."""
from typing import List, Dict, Optional
from datetime import datetime


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
        interview_start_language: Optional[str] = None
    ):
        """
        Initialize a new conversation.
        
        Args:
            job_offer_description: Full job offer description for context
            candidate_cv_text: Parsed text from candidate's CV
            job_title: Title of the job position
            required_languages: JSON string array of required languages
            interview_start_language: Language to start the interview with
        """
        self.history: List[Dict[str, str]] = []
        self.created_at = datetime.now()
        self.job_offer_description = job_offer_description
        self.candidate_cv_text = candidate_cv_text
        self.job_title = job_title
        self.required_languages = required_languages
        self.interview_start_language = interview_start_language
        self.phase = self.PHASE_AUDIO_CHECK  # Start with audio check
        self.candidate_name: Optional[str] = None
        self.candidate_name_spelling: Optional[str] = None
    
    def get_interview_context(self) -> Dict[str, Optional[str]]:
        """Get the interview context (job offer and candidate profile)."""
        return {
            "job_title": self.job_title,
            "job_offer_description": self.job_offer_description,
            "candidate_cv_text": self.candidate_cv_text,
            "required_languages": self.required_languages,
            "interview_start_language": self.interview_start_language
        }
    
    def get_current_phase(self) -> str:
        """Get the current conversation phase."""
        return self.phase
    
    def set_phase(self, phase: str):
        """Set the conversation phase."""
        self.phase = phase
    
    def set_candidate_name(self, name: str, spelling: Optional[str] = None):
        """Store the candidate's name and spelling."""
        self.candidate_name = name
        self.candidate_name_spelling = spelling
    
    def get_candidate_name(self) -> Optional[str]:
        """Get the candidate's name."""
        return self.candidate_name
    
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
