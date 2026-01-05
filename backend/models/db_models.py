"""Database models for the application."""
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import uuid
from backend.database import Base


def generate_id():
    """Generate a unique ID."""
    return f"{uuid.uuid4().hex[:12]}"


class JobOffer(Base):
    """Job offer model."""
    __tablename__ = "job_offers"

    offer_id = Column(String, primary_key=True, default=generate_id)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    required_skills = Column(Text, default="")
    experience_level = Column(String, default="")
    education_requirements = Column(Text, default="")
    required_languages = Column(Text, default="")  # JSON array of languages, e.g., ["English", "French"]
    interview_start_language = Column(String, default="")  # Language to start the interview with
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    applications = relationship("Application", back_populates="job_offer", cascade="all, delete-orphan")


class Candidate(Base):
    """Candidate model - stores unique candidate information."""
    __tablename__ = "candidates"

    candidate_id = Column(String, primary_key=True, default=generate_id)
    email = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    phone = Column(String)
    linkedin = Column(String)
    portfolio = Column(String)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    applications = relationship("Application", back_populates="candidate", cascade="all, delete-orphan")


class Application(Base):
    """Application model - links candidates to job offers."""
    __tablename__ = "applications"

    application_id = Column(String, primary_key=True, default=generate_id)
    candidate_id = Column(String, ForeignKey("candidates.candidate_id"), nullable=False)
    job_offer_id = Column(String, ForeignKey("job_offers.offer_id"), nullable=False, index=True)
    
    # Application data
    cover_letter = Column(Text, default="")  # Can be text or filename if uploaded as file
    cover_letter_filename = Column(String)  # Filename if cover letter is uploaded as document
    cv_text = Column(Text, nullable=False)  # Parsed CV text
    cv_filename = Column(String)
    
    # AI Evaluation
    ai_status = Column(String, default="pending")  # "approved", "rejected", "pending"
    ai_reasoning = Column(Text, default="")
    ai_score = Column(Integer, default=0)
    ai_skills_match = Column(Integer, default=0)
    ai_experience_match = Column(Integer, default=0)
    ai_education_match = Column(Integer, default=0)
    
    # HR Status
    hr_status = Column(String, default="pending")  # "pending", "selected", "rejected", "interview_sent"
    hr_override_reason = Column(Text, default="")
    
    # Interview
    interview_invited_at = Column(DateTime, nullable=True)
    interview_completed_at = Column(DateTime, nullable=True)
    interview_assessment = Column(Text, nullable=True)
    interview_recommendation = Column(String, nullable=True)  # "recommended", "not_recommended", null
    
    # Timestamps
    submitted_at = Column(DateTime, default=func.now())
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # Relationships
    candidate = relationship("Candidate", back_populates="applications")
    job_offer = relationship("JobOffer", back_populates="applications")
    interviews = relationship("Interview", back_populates="application", cascade="all, delete-orphan")


class CVEvaluation(Base):
    """CV Evaluation model - stores CV evaluation results."""
    __tablename__ = "cv_evaluations"

    evaluation_id = Column(String, primary_key=True, default=generate_id)
    application_id = Column(String, ForeignKey("applications.application_id"), nullable=True, index=True)
    job_offer_id = Column(String, ForeignKey("job_offers.offer_id"), nullable=False)
    
    status = Column(String, nullable=False)  # "approved", "rejected"
    score = Column(Integer, default=0)
    skills_match = Column(Integer, default=0)
    experience_match = Column(Integer, default=0)
    education_match = Column(Integer, default=0)
    reasoning = Column(Text, nullable=False)
    cv_text_length = Column(Integer, default=0)
    parsed_cv_text = Column(Text, nullable=False)
    
    created_at = Column(DateTime, default=func.now())

    # Relationships
    application = relationship("Application", foreign_keys=[application_id])


class Interview(Base):
    """Interview model - stores interview records and assessments."""
    __tablename__ = "interviews"

    interview_id = Column(String, primary_key=True, default=generate_id)
    application_id = Column(String, ForeignKey("applications.application_id"), nullable=True, index=True)
    job_offer_id = Column(String, ForeignKey("job_offers.offer_id"), nullable=False)
    
    # Interview data
    conversation_history = Column(Text, nullable=True)  # JSON string of conversation
    assessment = Column(Text, nullable=True)  # Full assessment text
    recommendation = Column(String, nullable=True)  # "recommended", "not_recommended"
    candidate_name = Column(String, nullable=True)
    cv_text = Column(Text, nullable=True)  # Reference to CV text used
    
    # Detailed evaluation scores (stored as JSON string)
    evaluation_scores = Column(Text, nullable=True)  # JSON with detailed scores per axis
    # Example: {"technical_skills": 8, "job_fit": 7, "communication": 9, "problem_solving": 8, "cv_consistency": 7, "linguistic_capacity": {"English": 9, "French": 8}, "overall_score": 7.8}
    
    # Status
    status = Column(String, default="pending")  # "pending", "completed", "cancelled"
    
    # Timestamps
    created_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    application = relationship("Application", back_populates="interviews")


class Admin(Base):
    """Admin model - stores admin user credentials."""
    __tablename__ = "admins"

    admin_id = Column(String, primary_key=True, default=generate_id)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)  # Hashed password
    email = Column(String, unique=True, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    last_login = Column(DateTime, nullable=True)




