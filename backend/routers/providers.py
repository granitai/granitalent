"""Provider configuration routes."""
from fastapi import APIRouter

from backend.config import (
    DEFAULT_TTS_PROVIDER,
    DEFAULT_STT_PROVIDER,
    DEFAULT_LLM_PROVIDER,
)

router = APIRouter(prefix="/api", tags=["Providers"])


@router.get("/elevenlabs/status")
async def check_elevenlabs_status():
    """Check ElevenLabs account status and credits."""
    from backend.services.elevenlabs_account_check import check_account_status
    return check_account_status()


@router.get("/providers")
async def get_providers():
    """Get available voices for interview setup."""
    from backend.config import OPENAI_REALTIME_VOICES, OPENAI_REALTIME_VOICE
    return {
        "realtime": {
            "voices": [{"id": k, "name": v} for k, v in OPENAI_REALTIME_VOICES.items()],
            "default_voice": OPENAI_REALTIME_VOICE,
        },
        # Legacy alias for frontend compatibility
        "gemini_live": {
            "voices": [{"id": k, "name": v} for k, v in OPENAI_REALTIME_VOICES.items()],
            "default_voice": OPENAI_REALTIME_VOICE,
        },
        "defaults": {
            "tts_provider": DEFAULT_TTS_PROVIDER,
            "stt_provider": DEFAULT_STT_PROVIDER,
            "llm_provider": DEFAULT_LLM_PROVIDER,
        },
    }
