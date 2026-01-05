"""Job offer data model and storage."""
from typing import Dict, Optional
from datetime import datetime
import uuid

# In-memory storage for job offers
# In production, this would be a database
job_offers: Dict[str, Dict] = {}


class JobOffer:
    """Represents a job or internship offer."""
    
    def __init__(
        self,
        title: str,
        description: str,
        required_skills: str = "",
        experience_level: str = "",
        education_requirements: str = "",
        offer_id: Optional[str] = None
    ):
        """
        Initialize a job offer.
        
        Args:
            title: Job title
            description: Job description
            required_skills: Required skills (comma-separated or free text)
            experience_level: Required experience level
            education_requirements: Education requirements
            offer_id: Optional ID (auto-generated if not provided)
        """
        self.offer_id = offer_id or f"offer_{uuid.uuid4().hex[:12]}"
        self.title = title
        self.description = description
        self.required_skills = required_skills
        self.experience_level = experience_level
        self.education_requirements = education_requirements
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        """Convert job offer to dictionary."""
        return {
            "offer_id": self.offer_id,
            "title": self.title,
            "description": self.description,
            "required_skills": self.required_skills,
            "experience_level": self.experience_level,
            "education_requirements": self.education_requirements,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'JobOffer':
        """Create JobOffer from dictionary."""
        offer = cls(
            title=data["title"],
            description=data["description"],
            required_skills=data.get("required_skills", ""),
            experience_level=data.get("experience_level", ""),
            education_requirements=data.get("education_requirements", ""),
            offer_id=data.get("offer_id")
        )
        offer.created_at = data.get("created_at", offer.created_at)
        offer.updated_at = data.get("updated_at", offer.updated_at)
        return offer
    
    def get_full_description(self) -> str:
        """Get full job description formatted for LLM evaluation."""
        parts = [f"Job Title: {self.title}"]
        
        if self.description:
            parts.append(f"\nDescription:\n{self.description}")
        
        if self.required_skills:
            parts.append(f"\nRequired Skills:\n{self.required_skills}")
        
        if self.experience_level:
            parts.append(f"\nExperience Level: {self.experience_level}")
        
        if self.education_requirements:
            parts.append(f"\nEducation Requirements:\n{self.education_requirements}")
        
        return "\n".join(parts)


def create_job_offer(
    title: str,
    description: str,
    required_skills: str = "",
    experience_level: str = "",
    education_requirements: str = ""
) -> JobOffer:
    """Create and store a new job offer."""
    offer = JobOffer(
        title=title,
        description=description,
        required_skills=required_skills,
        experience_level=experience_level,
        education_requirements=education_requirements
    )
    job_offers[offer.offer_id] = offer.to_dict()
    return offer


def get_job_offer(offer_id: str) -> Optional[JobOffer]:
    """Get a job offer by ID."""
    if offer_id in job_offers:
        return JobOffer.from_dict(job_offers[offer_id])
    return None


def get_all_job_offers() -> list[JobOffer]:
    """Get all job offers."""
    return [JobOffer.from_dict(data) for data in job_offers.values()]


def update_job_offer(offer_id: str, **kwargs) -> Optional[JobOffer]:
    """Update a job offer."""
    if offer_id not in job_offers:
        return None
    
    data = job_offers[offer_id].copy()
    data.update(kwargs)
    data["updated_at"] = datetime.now().isoformat()
    
    offer = JobOffer.from_dict(data)
    job_offers[offer_id] = offer.to_dict()
    return offer


def delete_job_offer(offer_id: str) -> bool:
    """Delete a job offer."""
    if offer_id in job_offers:
        del job_offers[offer_id]
        return True
    return False
