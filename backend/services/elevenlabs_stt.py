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

# Initialize the ElevenLabs client
client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

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
