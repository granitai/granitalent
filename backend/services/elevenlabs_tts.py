"""ElevenLabs Text-to-Speech service using official library."""
import logging
import time
import socket
from typing import Optional
from elevenlabs import ElevenLabs
from backend.config import ELEVENLABS_API_KEY, TTS_PROVIDERS, DEFAULT_TTS_PROVIDER, DEFAULT_VOICE_ID

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
    return ElevenLabs(api_key=api_key)

# Get default model
DEFAULT_TTS_MODEL = TTS_PROVIDERS[DEFAULT_TTS_PROVIDER]["default_model"]

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds


def text_to_speech(
    text: str, 
    voice_id: Optional[str] = None,
    model_id: Optional[str] = None
) -> bytes:
    """
    Convert text to speech using ElevenLabs TTS API.
    
    Args:
        text: The text to convert to speech
        voice_id: The voice ID to use (defaults to DEFAULT_VOICE_ID)
        model_id: The TTS model to use (defaults to config default)
    
    Returns:
        Audio bytes in MP3 format
    
    Raises:
        Exception: If TTS fails after all retries
    """
    if voice_id is None:
        voice_id = DEFAULT_VOICE_ID
    
    if model_id is None:
        model_id = DEFAULT_TTS_MODEL
    
    logger.info(f"🔊 ElevenLabs TTS: Using model '{model_id}' with voice '{voice_id}'")
    logger.info(f"🔊 ElevenLabs TTS: Converting text: '{text[:50]}...'" if len(text) > 50 else f"🔊 ElevenLabs TTS: Converting text: '{text}'")
    
    last_error = None
    
    for attempt in range(MAX_RETRIES):
        try:
            # Get client with current API key
            client = get_client()
            # Generate audio using the official library
            audio_generator = client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id=model_id,
                output_format="mp3_44100_128"
            )
            
            # Collect all audio chunks into bytes
            audio_bytes = b"".join(audio_generator)
            
            logger.info(f"🔊 ElevenLabs TTS: Generated {len(audio_bytes)} bytes of audio")
            
            return audio_bytes
            
        except (socket.gaierror, OSError) as e:
            last_error = e
            error_code = getattr(e, 'errno', None)
            
            # DNS resolution errors (11001, 11002 on Windows)
            if error_code in (11001, 11002) or 'getaddrinfo' in str(e):
                logger.warning(f"🔄 ElevenLabs TTS: DNS error on attempt {attempt + 1}/{MAX_RETRIES}: {e}")
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
                    "4. Switch to Cartesia TTS provider in the interview settings (uses different credit system)",
                    "\nCheck your account status: Visit https://elevenlabs.io/app/settings/api-keys"
                ]
                error_msg = "\n".join(error_msg_parts)
                logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg) from e
            
            logger.warning(f"🔄 ElevenLabs TTS: Error on attempt {attempt + 1}/{MAX_RETRIES}: {e}")
            if attempt < MAX_RETRIES - 1:
                wait_time = RETRY_DELAY * (2 ** attempt)
                logger.info(f"⏳ Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                continue
            raise
    
    # If we get here, all retries failed
    error_msg = f"ElevenLabs TTS failed after {MAX_RETRIES} attempts. Please check your internet connection and try again."
    logger.error(f"❌ {error_msg} Last error: {last_error}")
    raise Exception(error_msg)
