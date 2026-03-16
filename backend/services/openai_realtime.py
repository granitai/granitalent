"""OpenAI Realtime API service for real-time audio conversation.

Drop-in replacement for GeminiLiveSession. Uses OpenAI's Realtime API
(WebSocket) for native audio-in/audio-out conversation with semantic VAD,
built-in noise reduction, and high-quality transcription.
"""
import json
import base64
import logging
import asyncio
import struct
from typing import Optional, Callable, List

import websockets

logger = logging.getLogger(__name__)

OPENAI_REALTIME_WS_BASE = "wss://api.openai.com/v1/realtime"

# Voices available in OpenAI Realtime
OPENAI_REALTIME_VOICES = {
    "alloy": "Alloy — Neutral & Balanced",
    "ash": "Ash — Warm & Confident",
    "ballad": "Ballad — Soft & Gentle",
    "coral": "Coral — Friendly & Upbeat",
    "echo": "Echo — Deep & Resonant",
    "sage": "Sage — Calm & Measured",
    "shimmer": "Shimmer — Bright & Energetic",
    "verse": "Verse — Versatile & Expressive",
}

DEFAULT_VOICE = "sage"


def _resample_16k_to_24k(pcm_16k_bytes: bytes) -> bytes:
    """Resample 16kHz 16-bit PCM to 24kHz using linear interpolation."""
    if not pcm_16k_bytes:
        return b""
    n_samples = len(pcm_16k_bytes) // 2
    if n_samples == 0:
        return b""
    samples_16k = struct.unpack(f'<{n_samples}h', pcm_16k_bytes)
    # 24000/16000 = 1.5x samples
    n_out = int(n_samples * 1.5)
    samples_24k = []
    for i in range(n_out):
        src_pos = i / 1.5
        idx = int(src_pos)
        frac = src_pos - idx
        if idx + 1 < n_samples:
            val = samples_16k[idx] * (1 - frac) + samples_16k[idx + 1] * frac
        else:
            val = samples_16k[min(idx, n_samples - 1)]
        val = max(-32768, min(32767, int(val)))
        samples_24k.append(val)
    return struct.pack(f'<{len(samples_24k)}h', *samples_24k)


class OpenAIRealtimeSession:
    """Manages a real-time audio session with the OpenAI Realtime API.

    Provides the same interface as GeminiLiveSession for drop-in replacement.
    """

    def __init__(
        self,
        api_key: str,
        model: str = None,
        system_prompt: str = "",
        voice: str = DEFAULT_VOICE,
        language: str = "en",
    ):
        import os
        self.api_key = api_key
        self.model = model or os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime")
        self.system_prompt = system_prompt
        self.voice = voice
        self.language = language
        # VAD threshold (0-1): higher = less sensitive to noise, but may miss quiet speech.
        # 0.5 = OpenAI default. Tunable via VAD_THRESHOLD env var.
        self.vad_threshold = float(os.getenv("VAD_THRESHOLD", "0.5"))
        # Silence duration before ending the turn. 500ms = OpenAI default.
        # Tunable via VAD_SILENCE_MS env var.
        self.vad_silence_ms = int(os.getenv("VAD_SILENCE_MS", "500"))
        self.ws = None
        self.connected = False
        self.ai_text_parts: List[str] = []
        self._receive_task: Optional[asyncio.Task] = None

        # Track current response for interruption handling
        self._current_response_id: Optional[str] = None
        self._current_item_id: Optional[str] = None

        # Callbacks — same interface as GeminiLiveSession
        self._on_audio: Optional[Callable] = None
        self._on_text: Optional[Callable] = None
        self._on_turn_complete: Optional[Callable] = None
        self._on_interrupted: Optional[Callable] = None
        self._on_input_transcription: Optional[Callable] = None
        self._on_output_transcription: Optional[Callable] = None
        self._on_interview_end: Optional[Callable] = None

    # ------------------------------------------------------------------
    # Callback registration (identical to GeminiLiveSession)
    # ------------------------------------------------------------------
    def on_audio(self, cb: Callable):
        self._on_audio = cb

    def on_text(self, cb: Callable):
        self._on_text = cb

    def on_turn_complete(self, cb: Callable):
        self._on_turn_complete = cb

    def on_interrupted(self, cb: Callable):
        self._on_interrupted = cb

    def on_input_transcription(self, cb: Callable):
        self._on_input_transcription = cb

    def on_output_transcription(self, cb: Callable):
        self._on_output_transcription = cb

    def on_interview_end(self, cb: Callable):
        self._on_interview_end = cb

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    async def connect(self):
        """Connect to OpenAI Realtime WebSocket and configure the session."""
        url = f"{OPENAI_REALTIME_WS_BASE}?model={self.model}"
        logger.info(f"Connecting to OpenAI Realtime ({self.model})...")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        self.ws = await websockets.connect(
            url,
            additional_headers=headers,
            max_size=16 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=60,
        )

        # Wait for session.created
        raw = await self.ws.recv()
        created = json.loads(raw)
        if created.get("type") != "session.created":
            logger.warning(f"Expected session.created, got: {created.get('type')}")

        # Configure the session
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": self.system_prompt,
                "voice": self.voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "gpt-4o-transcribe",
                    # No "language" parameter — let gpt-4o-transcribe auto-detect
                    # the spoken language. This is critical for multi-language
                    # interviews where the candidate switches between languages.
                },
                "turn_detection": {
                    "type": "server_vad",
                    # Threshold (0-1): how loud audio must be to count as speech.
                    # 0.5 = OpenAI default. Tunable via VAD_THRESHOLD env var.
                    "threshold": self.vad_threshold,
                    # Audio to keep before detected speech start (avoids clipping first syllable)
                    "prefix_padding_ms": 300,
                    # Silence duration before ending the turn. 500ms = OpenAI default.
                    # Tunable via VAD_SILENCE_MS env var.
                    "silence_duration_ms": self.vad_silence_ms,
                    "create_response": True,
                    "interrupt_response": True,
                },
                "input_audio_noise_reduction": {
                    "type": "far_field",
                },
                "tools": [
                    {
                        "type": "function",
                        "name": "end_interview",
                        "description": (
                            "Call this function when the interview is finished. "
                            "You MUST call this after you have said your final goodbye/farewell to the candidate. "
                            "CRITICAL: You must have received the candidate's answer to your LAST question before calling this. "
                            "Never call this right after asking a question — always wait for the answer first, then say goodbye, then call this. "
                            "Triggers: time is up, or the candidate asks to end. "
                            "IMPORTANT: Do NOT call this on your own to end the interview early. "
                            "The system will tell you when it is time to end. Just keep asking questions until told otherwise."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "reason": {
                                    "type": "string",
                                    "description": "Why the interview ended, e.g. 'all_questions_asked', 'time_up', 'candidate_requested'"
                                }
                            },
                            "required": ["reason"]
                        }
                    }
                ],
                "tool_choice": "auto",
                "temperature": 0.7,
            }
        }

        await self.ws.send(json.dumps(session_config))

        # Wait for session.updated confirmation
        raw = await self.ws.recv()
        updated = json.loads(raw)
        if updated.get("type") == "session.updated":
            logger.info("OpenAI Realtime session configured")
        else:
            logger.warning(f"Expected session.updated, got: {updated.get('type')}")

        self.connected = True
        self._receive_task = asyncio.create_task(self._receive_loop())
        return updated

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    async def send_audio(self, pcm_base64_16k: str):
        """Forward a PCM-16kHz audio chunk (base64) to OpenAI.

        OpenAI Realtime expects 24kHz PCM, so we resample on the fly.
        """
        if not self.ws or not self.connected:
            return
        try:
            # Decode 16kHz PCM, resample to 24kHz, re-encode
            pcm_16k = base64.b64decode(pcm_base64_16k)
            pcm_24k = _resample_16k_to_24k(pcm_16k)
            pcm_24k_b64 = base64.b64encode(pcm_24k).decode("ascii")

            await self.ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": pcm_24k_b64,
            }))
        except Exception as e:
            if self.connected:
                logger.error(f"send_audio error: {e}")
                self.connected = False

    async def send_text(self, text: str):
        """Send a text message and force an immediate response.

        Equivalent to Gemini's turnComplete=True. We add the text as a
        conversation item and then trigger a response.
        """
        if not self.ws or not self.connected:
            return
        try:
            # Add user message to conversation
            await self.ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}]
                }
            }))
            # Trigger response
            await self.ws.send(json.dumps({
                "type": "response.create",
            }))
        except Exception as e:
            if self.connected:
                logger.error(f"send_text error: {e}")
                self.connected = False

    async def send_context(self, text: str):
        """Buffer a text instruction into the conversation context WITHOUT triggering a response.

        Equivalent to Gemini's turnComplete=False. We add the text as a system
        message but don't call response.create — the model will see it when
        the next user audio turn completes.
        """
        if not self.ws or not self.connected:
            return
        try:
            await self.ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}]
                }
            }))
        except Exception as e:
            if self.connected:
                logger.error(f"send_context error: {e}")
                self.connected = False

    # ------------------------------------------------------------------
    # Receiving (background loop)
    # ------------------------------------------------------------------
    async def _receive_loop(self):
        try:
            async for raw in self.ws:
                try:
                    event = json.loads(raw)
                    await self._dispatch(event)
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    logger.error(f"OpenAI Realtime dispatch error: {e}")
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"OpenAI Realtime connection closed: code={e.code}, reason='{e.reason}'")
        except Exception as e:
            if self.connected:
                logger.error(f"OpenAI Realtime receive error: {e}")
        finally:
            self.connected = False

    async def _dispatch(self, event: dict):
        event_type = event.get("type", "")

        # --- Audio output (AI speaking) ---
        if event_type == "response.audio.delta":
            audio_b64 = event.get("delta", "")
            if audio_b64 and self._on_audio:
                # OpenAI sends 24kHz PCM — same as what our frontend expects
                await self._on_audio(audio_b64)

        # --- AI output transcription (streamed) ---
        elif event_type == "response.audio_transcript.delta":
            text = event.get("delta", "")
            if text and self._on_output_transcription:
                await self._on_output_transcription(text)

        # --- User input transcription (completed) ---
        elif event_type == "conversation.item.input_audio_transcription.completed":
            text = event.get("transcript", "")
            if text and self._on_input_transcription:
                await self._on_input_transcription(text)

        # --- Response done (turn complete) ---
        elif event_type == "response.done":
            response = event.get("response", {})
            # Check for function calls in the response output
            for item in response.get("output", []):
                if item.get("type") == "function_call":
                    await self._handle_function_call(item)
                    return  # Don't fire turn_complete for function call turns

            # Normal turn complete (AI finished speaking)
            if self._on_turn_complete:
                await self._on_turn_complete()

        # --- User started speaking (VAD detected speech) ---
        elif event_type == "input_audio_buffer.speech_started":
            # Fires whenever speech is detected — both during AI output (interruption)
            # and during normal turn-taking after AI finishes
            if self._on_interrupted:
                await self._on_interrupted()

        # --- User stopped speaking (VAD detected silence) ---
        elif event_type == "input_audio_buffer.speech_stopped":
            pass  # Turn completion handled by response.done + input transcription

        # --- Error ---
        elif event_type == "error":
            error = event.get("error", {})
            logger.error(f"OpenAI Realtime error: {error.get('message', 'unknown')} (code={error.get('code')})")

        # --- Rate limits ---
        elif event_type == "rate_limits.updated":
            pass  # Silently handle rate limit updates

    async def _handle_function_call(self, item: dict):
        """Handle a function call from the model."""
        fn_name = item.get("name", "")
        fn_args_str = item.get("arguments", "{}")
        call_id = item.get("call_id", "")

        try:
            fn_args = json.loads(fn_args_str)
        except json.JSONDecodeError:
            fn_args = {}

        logger.info(f"OpenAI Realtime tool call: {fn_name}({fn_args})")

        if fn_name == "end_interview":
            reason = fn_args.get("reason", "ai_decided")
            should_end = True
            rejection_reason = "The interview is not finished yet. Continue asking questions."

            if self._on_interview_end:
                result = await self._on_interview_end(reason)
                if result is False:
                    should_end = False
                elif isinstance(result, dict):
                    should_end = False
                    rejection_reason = result.get("reason", rejection_reason)

            if should_end:
                # Send the function result but DON'T trigger response.create —
                # the farewell was already spoken in the same response that called
                # end_interview. Triggering another response would cause a double-goodbye.
                await self._send_function_result_no_continue(call_id, json.dumps({"status": "ok"}))
                # Manually fire turn_complete so the farewell text gets processed
                if self._on_turn_complete:
                    await self._on_turn_complete()
            else:
                await self._send_function_result(
                    call_id,
                    json.dumps({"status": "rejected", "reason": rejection_reason})
                )
        else:
            # Unknown function
            await self._send_function_result(
                call_id,
                json.dumps({"error": "unknown_function"})
            )

    async def _send_function_result(self, call_id: str, output: str):
        """Send a function call result back to OpenAI and trigger continuation."""
        if not self.ws or not self.connected:
            return
        try:
            # Send function output
            await self.ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                }
            }))
            # Trigger model to continue with the result
            await self.ws.send(json.dumps({
                "type": "response.create",
            }))
        except Exception as e:
            logger.error(f"Error sending function result: {e}")

    async def _send_function_result_no_continue(self, call_id: str, output: str):
        """Send a function call result WITHOUT triggering a new response.

        Used for accepted end_interview — the farewell was already spoken,
        so we don't want the model to generate another response."""
        if not self.ws or not self.connected:
            return
        try:
            await self.ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                }
            }))
        except Exception as e:
            logger.error(f"Error sending function result: {e}")

    # ------------------------------------------------------------------
    # Transcript & cleanup
    # ------------------------------------------------------------------
    def get_ai_transcript(self) -> str:
        return " ".join(self.ai_text_parts)

    async def close(self):
        self.connected = False
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        logger.info("OpenAI Realtime session closed")
