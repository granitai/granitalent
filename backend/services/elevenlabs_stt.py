"""ElevenLabs Speech-to-Text service using official library."""
import logging
import time
import socket
from io import BytesIO
from typing import Optional
from elevenlabs import ElevenLabs
from backend.config import ELEVENLABS_API_KEY, STT_MODEL

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Don't initialize client at module level - create it dynamically to always use current API key
def get_client():
    """Get ElevenLabs client with current API key (reloads from .env file)."""
    from dotenv import load_dotenv
    import os
    # Reload .env file to get latest API key
    load_dotenv(override=True)  # override=True ensures new values replace old ones
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY not found in environment variables. Please check your .env file.")
    return ElevenLabs(api_key=api_key)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds


def speech_to_text(audio_bytes: bytes, audio_format: str = "webm", model_id: Optional[str] = None) -> str:
    """
    Convert speech to text using ElevenLabs STT API.
    
    Args:
        audio_bytes: The audio data as bytes
        audio_format: The format of the audio (webm, mp3, wav, etc.)
        model_id: The STT model to use (scribe_v1 or scribe_v2). Defaults to config.
    
    Returns:
        Transcribed text
    
    Raises:
        Exception: If STT fails after all retries
    """
    # Use provided model or fall back to config default
    if model_id is None:
        model_id = STT_MODEL
    
    logger.info(f"🎤 STT: Using model '{model_id}' for transcription")
    
    last_error = None
    
    for attempt in range(MAX_RETRIES):
        try:
            # Get client with current API key
            client = get_client()
            # Wrap audio bytes in BytesIO for the API (fresh copy for each attempt)
            audio_file = BytesIO(audio_bytes)
            
            # Transcribe audio using the official library
            result = client.speech_to_text.convert(
                file=audio_file,
                model_id=model_id
            )
            
            transcribed_text = result.text if result.text else ""
            logger.info(f"📝 STT: Transcribed text: '{transcribed_text[:50]}...' " if len(transcribed_text) > 50 else f"📝 STT: Transcribed text: '{transcribed_text}'")
            
            return transcribed_text
            
        except (socket.gaierror, OSError) as e:
            last_error = e
            error_code = getattr(e, 'errno', None)
            
            # DNS resolution errors (11001, 11002 on Windows)
            if error_code in (11001, 11002) or 'getaddrinfo' in str(e):
                logger.warning(f"🔄 ElevenLabs STT: DNS error on attempt {attempt + 1}/{MAX_RETRIES}: {e}")
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_DELAY * (2 ** attempt)  # Exponential backoff
                    logger.info(f"⏳ Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue
            else:
                raise
                
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            
            # Check for quota exceeded errors
            if "quota" in error_str or "quota_exceeded" in error_str or "credits" in error_str:
                # Extract credit information from error if available
                error_msg_parts = [
                    "ElevenLabs API quota exceeded - Monthly credit limit reached.\n",
                    "The error indicates you've used almost all of your monthly 10,000 credit quota.",
                    "Only 13 credits remain, but this request requires 16 credits.\n",
                    "\nSolutions:",
                    "1. Wait for your monthly quota to reset (check reset date in your ElevenLabs dashboard)",
                    "2. Enable 'Usage-Based Billing' in your ElevenLabs account settings to continue using credits beyond your monthly limit",
                    "3. Upgrade to a higher plan with more monthly credits",
                    "4. Switch to Cartesia STT provider in the interview settings (uses different credit system)",
                    "\nCheck your account status: Visit https://elevenlabs.io/app/settings/api-keys"
                ]
                error_msg = "\n".join(error_msg_parts)
                logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg) from e
            
            logger.warning(f"🔄 ElevenLabs STT: Error on attempt {attempt + 1}/{MAX_RETRIES}: {e}")
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
                logger.info(f"⏳ Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                continue
            raise
    
    # If we get here, all retries failed
    error_msg = f"ElevenLabs STT failed after {MAX_RETRIES} attempts. Please check your internet connection and try again."
    logger.error(f"❌ {error_msg} Last error: {last_error}")
    raise Exception(error_msg)
