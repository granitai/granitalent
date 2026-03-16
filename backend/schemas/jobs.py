"""Job offer request/response schemas."""
from typing import Optional, List
from pydantic import BaseModel


class JobOfferCreate(BaseModel):
    title: str
    description: str
    required_skills: str = ""
    experience_level: str = ""
    education_requirements: str = ""
    required_languages: str = ""  # JSON array string, e.g., '["English", "French"]'
    interview_start_language: str = ""
    interview_duration_minutes: int = 20  # Interview duration in minutes (default 20)
    custom_questions: str = ""  # JSON array of custom questions, e.g., '["What is your experience with X?"]'
    evaluation_weights: str = ""  # JSON object with weights, e.g., '{"technical_skills": 5, "language_proficiency": 10}'
    interview_mode: str = "realtime"  # "realtime" or "asynchronous"


class JobOfferUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    required_skills: Optional[str] = None
    experience_level: Optional[str] = None
    education_requirements: Optional[str] = None
    required_languages: Optional[str] = None
    interview_start_language: Optional[str] = None
    interview_duration_minutes: Optional[int] = None
    custom_questions: Optional[str] = None
    evaluation_weights: Optional[str] = None
    interview_mode: Optional[str] = None


class BulkJobOfferRequest(BaseModel):
    offer_ids: list
