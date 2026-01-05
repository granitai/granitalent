"""Cartesia Ink Speech-to-Text service using official SDK."""
import logging
from io import BytesIO
from typing import Optional
from cartesia import Cartesia
from backend.config import CARTESIA_API_KEY

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the Cartesia client
client = Cartesia(api_key=CARTESIA_API_KEY)

# Available Cartesia STT models
CARTESIA_STT_MODELS = {
    "ink-whisper": "Ink Whisper — Real-time Transcription",
}


def speech_to_text(
    audio_bytes: bytes, 
    audio_format: str = "webm",
    model_id: str = "ink-whisper",
    language: str = "en"
) -> str:
    """
    Convert speech to text using Cartesia Ink STT API.
    
    Args:
        audio_bytes: The audio data as bytes
        audio_format: The format of the audio (webm, wav, mp3, etc.)
        model_id: The STT model to use (ink-whisper)
        language: The language code (default: en)
    
    Returns:
        Transcribed text
    """
    logger.info(f"🎤 Cartesia STT: Using model '{model_id}' for transcription")
    logger.info(f"🎤 Cartesia STT: Processing {len(audio_bytes)} bytes of audio")
    
    try:
        # Use the official SDK for transcription
        # Create a file-like object from bytes
        audio_file = BytesIO(audio_bytes)
        audio_file.name = f"audio.{audio_format}"
        
        result = client.stt.transcribe(
            model=model_id,
            file=audio_file,
            language=language
        )
        
        transcribed_text = result.text if hasattr(result, 'text') else str(result)
        
        logger.info(f"📝 Cartesia STT: Transcribed text: '{transcribed_text[:50]}...'" if len(transcribed_text) > 50 else f"📝 Cartesia STT: Transcribed text: '{transcribed_text}'")
        
        return transcribed_text
        
    except Exception as e:
        logger.error(f"🎤 Cartesia STT Error: {e}")
        raise
