"""Cartesia Sonic Text-to-Speech service using official SDK."""
import logging
from typing import Optional
from cartesia import Cartesia
from backend.config import CARTESIA_API_KEY

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the Cartesia client
client = Cartesia(api_key=CARTESIA_API_KEY)

# Available Cartesia TTS models
CARTESIA_TTS_MODELS = {
    "sonic-2024-10-16": "Sonic 2 — High Quality",
    "sonic-english": "Sonic English — Optimized",
    "sonic": "Sonic — Standard",
}

# Default voice ID - using a known working Cartesia voice
# You can find more voices at https://play.cartesia.ai/
DEFAULT_CARTESIA_VOICE_ID = "79a125e8-cd45-4c13-8a67-188112f4dd22"  # British Lady


def text_to_speech(
    text: str, 
    voice_id: Optional[str] = None, 
    model_id: str = "sonic"
) -> bytes:
    """
    Convert text to speech using Cartesia Sonic TTS API.
    
    Args:
        text: The text to convert to speech
        voice_id: The voice ID to use (defaults to DEFAULT_CARTESIA_VOICE_ID)
        model_id: The TTS model to use
    
    Returns:
        Audio bytes in WAV format
    """
    if voice_id is None:
        voice_id = DEFAULT_CARTESIA_VOICE_ID
    
    logger.info(f"🔊 Cartesia TTS: Using model '{model_id}' with voice '{voice_id}'")
    logger.info(f"🔊 Cartesia TTS: Converting text: '{text[:50]}...'" if len(text) > 50 else f"🔊 Cartesia TTS: Converting text: '{text}'")
    
    try:
        # Use the official SDK to generate audio
        # Voice must be passed as a dictionary with mode and id
        # The SDK returns a generator, so we need to consume it to get bytes
        audio_generator = client.tts.bytes(
            model_id=model_id,
            transcript=text,
            voice={
                "mode": "id",
                "id": voice_id
            },
            output_format={
                "container": "wav",
                "encoding": "pcm_s16le", 
                "sample_rate": 44100
            }
        )
        
        # Consume the generator and join all chunks into bytes
        audio_data = b"".join(audio_generator)
        
        logger.info(f"🔊 Cartesia TTS: Generated {len(audio_data)} bytes of audio")
        return audio_data
        
    except Exception as e:
        logger.error(f"🔊 Cartesia TTS Error: {e}")
        raise


def get_available_voices() -> list:
    """
    Get list of available Cartesia voices.
    
    Returns:
        List of voice dictionaries with id and name
    """
    try:
        voices = client.voices.list()
        return voices
    except Exception as e:
        logger.error(f"Failed to get voices: {e}")
        return []
