"""ElevenLabs Speech-to-Text Streaming service using WebSocket."""
import asyncio
import json
import logging
import base64
import io
from typing import Optional, Callable, AsyncGenerator
import websockets
from backend.config import ELEVENLABS_API_KEY

# Setup logging first
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import pydub for audio conversion
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logger.warning("⚠️ pydub not available - WebM to PCM conversion may not work. Install with: pip install pydub")

# Logging is set up above

# ElevenLabs STT Streaming WebSocket URL
ELEVENLABS_STT_WS_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"

# Available models for streaming
ELEVENLABS_STT_STREAMING_MODELS = {
    "scribe_v2": "Scribe v2 — Low Latency Streaming",
}


class ElevenLabsSTTStreaming:
    """
    ElevenLabs Speech-to-Text Streaming client using WebSocket.
    
    This class manages a WebSocket connection to ElevenLabs for real-time
    speech transcription as audio chunks are received.
    """
    
    def __init__(
        self,
        model_id: str = "scribe_v2_realtime",
        language: str = "en",
        sample_rate: int = 16000,
        on_interim_transcript: Optional[Callable[[str], None]] = None,
        on_final_transcript: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the streaming STT client.
        
        Args:
            model_id: The STT model to use
            language: Language code for transcription
            sample_rate: Audio sample rate in Hz
            on_interim_transcript: Callback for interim (partial) transcripts
            on_final_transcript: Callback for final transcripts
        """
        self.model_id = model_id
        self.language = language
        self.sample_rate = sample_rate
        self.on_interim_transcript = on_interim_transcript
        self.on_final_transcript = on_final_transcript
        
        self.websocket = None
        self.is_connected = False
        self.full_transcript = ""
        self._receive_task = None
        
    async def connect(self) -> bool:
        """
        Establish WebSocket connection to ElevenLabs STT service.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Reload API key from .env file to get latest value
            from dotenv import load_dotenv
            import os
            load_dotenv(override=True)  # override=True ensures new values replace old ones
            api_key = os.getenv("ELEVENLABS_API_KEY")
            
            # Validate API key
            if not api_key:
                logger.error("❌ ELEVENLABS_API_KEY is not set")
                return False
            
            # Build URL with required parameters
            # Note: model_id should be "scribe_v2_realtime" for the realtime API
            url = f"{ELEVENLABS_STT_WS_URL}?model_id={self.model_id}&language_code={self.language}"
            
            logger.info(f"🎤 Streaming STT: Connecting to ElevenLabs WebSocket...")
            logger.info(f"🎤 Streaming STT: URL: {url}")
            logger.info(f"🎤 Streaming STT: Model: {self.model_id}, Language: {self.language}")
            
            # Check websockets version and use appropriate header format
            websockets_version = getattr(websockets, '__version__', '0.0.0')
            logger.info(f"🎤 Streaming STT: Using websockets version {websockets_version}")
            
            # Version 12: extra_headers (dict)
            # Version 14+: additional_headers (list of tuples)
            if websockets_version.startswith('12.') or websockets_version.startswith('13.'):
                # Use extra_headers for v12/v13
                headers = {"xi-api-key": api_key}
                self.websocket = await websockets.connect(
                    url,
                    extra_headers=headers,
                    ping_interval=20,
                    ping_timeout=10,
                )
            else:
                # Use additional_headers for v14+
                headers = [("xi-api-key", api_key)]
                self.websocket = await websockets.connect(
                    url,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=10,
                )
            
            self.is_connected = True
            self.full_transcript = ""
            
            # Start receiving messages in background
            self._receive_task = asyncio.create_task(self._receive_messages())
            
            logger.info(f"🎤 Streaming STT: Connected successfully")
            return True
            
        except Exception as e:
            logger.error(f"🎤 Streaming STT: Connection failed: {e}")
            self.is_connected = False
            return False
    
    async def _receive_messages(self):
        """Background task to receive and process messages from WebSocket."""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning(f"🎤 Streaming STT: Received non-JSON message: {message[:100]}")
                    continue
                    
                message_type = data.get("message_type", data.get("type", ""))
                
                logger.info(f"🎤 Streaming STT: Received message type: '{message_type}'")
                
                if message_type == "partial_transcript" or message_type == "interim_transcript":
                    # Partial/interim transcript
                    transcript = data.get("text", data.get("transcript", ""))
                    if transcript:
                        logger.info(f"📝 Streaming STT: Partial transcript: '{transcript[:50]}...'")
                        if self.on_interim_transcript:
                            self.on_interim_transcript(transcript)
                        
                elif message_type == "committed_transcript" or message_type == "committed_transcript_with_timestamps":
                    # Final committed transcript
                    transcript = data.get("text", data.get("transcript", ""))
                    if transcript:
                        # Accumulate transcripts (in case there are multiple chunks)
                        if self.full_transcript:
                            self.full_transcript += " " + transcript
                        else:
                            self.full_transcript = transcript
                        logger.info(f"📝 Streaming STT: Committed transcript: '{transcript[:50]}...'")
                        logger.info(f"📝 Streaming STT: Full transcript so far: '{self.full_transcript[:100]}...'")
                        if self.on_final_transcript:
                            self.on_final_transcript(transcript)
                            
                elif message_type == "session_ended":
                    logger.info("🎤 Streaming STT: Session ended")
                    break
                    
                elif message_type == "error":
                    error_msg = data.get("error", data.get("message", "Unknown error"))
                    logger.error(f"🎤 Streaming STT Error: {error_msg}")
                    self.is_connected = False
                elif message_type == "session_started" or message_type == "session_ready":
                    logger.info(f"🎤 Streaming STT: Session started/ready")
                else:
                    # Log unknown message types for debugging
                    logger.info(f"🎤 Streaming STT: Received message type '{message_type}': {json.dumps(data)[:200]}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("🎤 Streaming STT: Connection closed")
        except Exception as e:
            logger.error(f"🎤 Streaming STT: Receive error: {e}")
    
    def _convert_webm_to_pcm(self, webm_audio: bytes) -> bytes:
        """
        Convert WebM audio to PCM format required by ElevenLabs API.
        
        Args:
            webm_audio: WebM audio bytes
            
        Returns:
            PCM audio bytes (16-bit, 16kHz, mono)
        """
        if not PYDUB_AVAILABLE:
            logger.warning("⚠️ pydub not available, cannot convert WebM to PCM")
            return webm_audio  # Return as-is, might fail
        
        try:
            # Load WebM audio
            audio = AudioSegment.from_file(io.BytesIO(webm_audio), format="webm")
            
            # Convert to required format: 16kHz, mono, 16-bit PCM
            audio = audio.set_frame_rate(self.sample_rate)
            audio = audio.set_channels(1)  # Mono
            audio = audio.set_sample_width(2)  # 16-bit
            
            # Export as raw PCM
            pcm_buffer = io.BytesIO()
            audio.export(pcm_buffer, format="raw")
            pcm_data = pcm_buffer.getvalue()
            
            logger.debug(f"🎤 Converted WebM ({len(webm_audio)} bytes) to PCM ({len(pcm_data)} bytes)")
            return pcm_data
            
        except Exception as e:
            error_msg = str(e)
            if "WinError 2" in error_msg or "Le fichier spécifié est introuvable" in error_msg or "ffmpeg" in error_msg.lower() or "ffprobe" in error_msg.lower():
                logger.error(f"🎤 ❌ CRITICAL: ffmpeg/ffprobe not found! Cannot convert WebM to PCM.")
                logger.error(f"🎤 📥 Install ffmpeg: https://ffmpeg.org/download.html")
                logger.error(f"🎤    Or use: winget install ffmpeg  (Windows)")
                logger.error(f"🎤    Audio conversion will fail until ffmpeg is installed.")
            else:
                logger.error(f"🎤 Error converting WebM to PCM: {e}")
            # Don't return original - it will fail anyway, but at least log the issue
            raise ValueError("WebM to PCM conversion failed - ffmpeg required. Install ffmpeg to use streaming STT.")
    
    async def send_audio_chunk(self, audio_chunk: bytes, commit: bool = False):
        """
        Send an audio chunk for transcription.
        
        Args:
            audio_chunk: Raw audio bytes (PCM or WebM - will be converted to PCM if needed)
            commit: Whether to commit this chunk (signal end of utterance)
        """
        if not self.is_connected or not self.websocket:
            logger.warning("🎤 Streaming STT: Not connected, cannot send audio")
            return
            
        try:
            # Convert WebM to PCM if needed (ElevenLabs API requires PCM)
            # This will raise an error if ffmpeg is not available
            pcm_audio = self._convert_webm_to_pcm(audio_chunk)
            
            audio_base64 = base64.b64encode(pcm_audio).decode('utf-8')
            
            message = {
                "message_type": "input_audio_chunk",
                "audio_base_64": audio_base64,
                "commit": commit,
                "sample_rate": self.sample_rate,
            }
            
            await self.websocket.send(json.dumps(message))
            
        except ValueError as e:
            # Conversion failed - don't send invalid audio
            logger.error(f"🎤 Streaming STT: Cannot send audio - {e}")
            raise
        except Exception as e:
            logger.error(f"🎤 Streaming STT: Send error: {e}")
            raise
    
    async def commit(self):
        """Signal end of audio stream and request final transcript."""
        if not self.is_connected or not self.websocket:
            return
            
        try:
            # Send an empty audio chunk with commit: true (API doesn't accept separate commit message)
            empty_pcm = b''  # Empty PCM data
            audio_base64 = base64.b64encode(empty_pcm).decode('utf-8')
            
            message = {
                "message_type": "input_audio_chunk",
                "audio_base_64": audio_base64,
                "commit": True,  # This commits the audio stream
                "sample_rate": self.sample_rate,
            }
            await self.websocket.send(json.dumps(message))
            logger.info("🎤 Streaming STT: Committed audio for final transcript")
            
        except Exception as e:
            logger.error(f"🎤 Streaming STT: Commit error: {e}")
    
    async def close(self):
        """Close the WebSocket connection."""
        self.is_connected = False
        
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
            
        if self.websocket:
            try:
                await self.websocket.close()
            except:
                pass
            self.websocket = None
            
        logger.info("🎤 Streaming STT: Connection closed")
    
    def get_transcript(self) -> str:
        """Get the accumulated transcript."""
        return self.full_transcript


async def transcribe_audio_stream(
    audio_chunks: AsyncGenerator[bytes, None],
    model_id: str = "scribe_v2",
    language: str = "en",
) -> str:
    """
    Convenience function to transcribe an async stream of audio chunks.
    
    Args:
        audio_chunks: Async generator yielding audio bytes
        model_id: STT model to use
        language: Language code
        
    Returns:
        Final transcript text
    """
    final_transcript = ""
    
    def on_final(transcript: str):
        nonlocal final_transcript
        final_transcript = transcript
    
    client = ElevenLabsSTTStreaming(
        model_id=model_id,
        language=language,
        on_final_transcript=on_final,
    )
    
    try:
        if await client.connect():
            async for chunk in audio_chunks:
                await client.send_audio_chunk(chunk)
            
            await client.commit()
            
            # Wait a bit for final transcript
            await asyncio.sleep(0.5)
            
    finally:
        await client.close()
    
    return final_transcript
