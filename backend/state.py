"""Shared in-memory state, constants, and directory configuration for the backend."""
import os

# Global list of phrases that confidently indicate the AI considers the interview finished.
# This list is used dynamically across all streaming/audio endpoint handlers.
CONCLUSION_PHRASES = [
    "this concludes",
    "that concludes",
    "will be processed",
    "thank you for participating",
    "thank you for your participation",
    "reached the end",
    "time is up",
    "we are out of time",
    "we're out of time",
    "thank you for your time",
    "thank you for coming",
    "any questions for me",
    "questions for me",
    "do you have any questions",
    "thank you for this interview",
    "hr team will review your application",
    "hr will review your application",
    "contact you soon",
    "get back to you soon"
]

# Language name -> ISO 639-1 code mapping for STT
LANGUAGE_TO_ISO = {
    "english": "en", "french": "fr", "arabic": "ar", "spanish": "es",
    "german": "de", "italian": "it", "portuguese": "pt", "dutch": "nl",
    "russian": "ru", "chinese": "zh", "japanese": "ja", "korean": "ko",
    "turkish": "tr", "polish": "pl", "swedish": "sv", "danish": "da",
    "norwegian": "no", "finnish": "fi", "czech": "cs", "greek": "el",
    "hindi": "hi", "thai": "th", "vietnamese": "vi", "indonesian": "id",
    "malay": "ms", "romanian": "ro", "hungarian": "hu", "ukrainian": "uk",
    "hebrew": "he", "persian": "fa", "bengali": "bn", "urdu": "ur",
}

# Ensure uploads directory exists -- use DATA_DIR if set (Docker), else local
_data_dir = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(_data_dir, "uploads")
VIDEOS_DIR = os.path.join(UPLOADS_DIR, "videos")
CVS_DIR = os.path.join(UPLOADS_DIR, "cvs")
os.makedirs(VIDEOS_DIR, exist_ok=True)
os.makedirs(CVS_DIR, exist_ok=True)

# Store active conversations (in production, use Redis or database)
active_conversations: dict = {}

# Store session configurations
session_configs: dict = {}

# Store active streaming STT sessions
streaming_stt_sessions: dict = {}

# Store interview start times for time limit tracking
interview_start_times: dict = {}

# Store CV evaluations (in production, use database)
cv_evaluations: dict = {}

# Store candidate applications (in production, use database)
candidate_applications: dict = {}

# Store last processed message hashes to prevent duplicates (conversation_id -> {hash: timestamp})
message_dedup_cache: dict = {}

# Deduplication window in seconds
MESSAGE_DEDUP_WINDOW = 5.0
