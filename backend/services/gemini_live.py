"""Gemini Live API service for real-time audio conversation.

Uses Google's Multimodal Live API (WebSocket) for native audio-in/audio-out
conversation. This collapses STT + LLM + TTS into a single round-trip,
achieving sub-second latency comparable to ChatGPT voice mode.
"""
import json
import logging
import asyncio
from typing import Optional, Callable, List

import websockets

logger = logging.getLogger(__name__)

GEMINI_LIVE_WS_BASE = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"

# Voices available in Gemini Live
GEMINI_LIVE_VOICES = {
    "Kore": "Kore — Clear & Professional",
    "Aoede": "Aoede — Warm & Friendly",
    "Puck": "Puck — Casual & Energetic",
    "Charon": "Charon — Deep & Authoritative",
    "Fenrir": "Fenrir — Confident",
    "Leda": "Leda — Soft & Calm",
}

DEFAULT_VOICE = "Kore"


class GeminiLiveSession:
    """Manages a real-time audio session with the Gemini Live API."""

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
        self.model = model or os.getenv("LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
        self.system_prompt = system_prompt
        self.voice = voice
        self.language = language
        self.ws = None
        self.connected = False
        self.ai_text_parts: List[str] = []
        self._receive_task: Optional[asyncio.Task] = None

        # Callbacks
        self._on_audio: Optional[Callable] = None
        self._on_text: Optional[Callable] = None
        self._on_turn_complete: Optional[Callable] = None
        self._on_interrupted: Optional[Callable] = None
        self._on_input_transcription: Optional[Callable] = None
        self._on_output_transcription: Optional[Callable] = None
        self._on_interview_end: Optional[Callable] = None

    # ------------------------------------------------------------------
    # Callback registration
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
        """Connect to Gemini Live WebSocket and send initial setup."""
        url = f"{GEMINI_LIVE_WS_BASE}?key={self.api_key}"
        logger.info(f"Connecting to Gemini Live ({self.model})...")

        self.ws = await websockets.connect(url, max_size=16 * 1024 * 1024, ping_interval=30)

        setup = {
            "setup": {
                "model": f"models/{self.model}",
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {"voiceName": self.voice}
                        }
                    },
                    "thinkingConfig": {
                        "thinkingBudget": 0
                    },
                },
                "systemInstruction": {
                    "parts": [{"text": self.system_prompt}]
                },
                "tools": [
                    {
                        "functionDeclarations": [
                            {
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
                        ]
                    }
                ],
                "realtimeInputConfig": {
                    "automaticActivityDetection": {
                        "disabled": False,
                        "startOfSpeechSensitivity": "START_SENSITIVITY_HIGH",
                        "endOfSpeechSensitivity": "END_SENSITIVITY_HIGH",
                        "prefixPaddingMs": 200,
                        "silenceDurationMs": 800,
                    }
                },
                "inputAudioTranscription": {},
                "outputAudioTranscription": {},
            }
        }

        await self.ws.send(json.dumps(setup))

        # Wait for setup acknowledgement
        raw = await self.ws.recv()
        ack = json.loads(raw)
        logger.info("Gemini Live session ready")

        self.connected = True
        self._receive_task = asyncio.create_task(self._receive_loop())
        return ack

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    async def send_audio(self, pcm_base64: str):
        """Forward a PCM-16kHz audio chunk (base64) to Gemini."""
        if not self.ws or not self.connected:
            return
        try:
            await self.ws.send(json.dumps({
                "realtimeInput": {
                    "mediaChunks": [{
                        "mimeType": "audio/pcm;rate=16000",
                        "data": pcm_base64,
                    }]
                }
            }))
        except Exception as e:
            logger.error(f"send_audio error: {e}")

    async def send_text(self, text: str):
        """Send a text message to the live session (e.g. for assessment).
        Uses turnComplete=True which forces Gemini to respond immediately."""
        if not self.ws or not self.connected:
            return
        try:
            await self.ws.send(json.dumps({
                "clientContent": {
                    "turns": [{"role": "user", "parts": [{"text": text}]}],
                    "turnComplete": True,
                }
            }))
        except Exception as e:
            logger.error(f"send_text error: {e}")

    async def send_context(self, text: str):
        """Buffer a text instruction into the conversation context WITHOUT triggering a response.

        Uses turnComplete=False so the content is buffered until the next natural
        turn completion (e.g., VAD detecting end-of-speech on realtimeInput audio).
        This allows injecting instructions (like language switch) that Gemini will
        process together with the candidate's next audio response, producing ONE
        natural combined response instead of forcing an immediate interruption.
        """
        if not self.ws or not self.connected:
            return
        try:
            await self.ws.send(json.dumps({
                "clientContent": {
                    "turns": [{"role": "user", "parts": [{"text": text}]}],
                    "turnComplete": False,
                }
            }))
        except Exception as e:
            logger.error(f"send_context error: {e}")

    # ------------------------------------------------------------------
    # Receiving (background loop)
    # ------------------------------------------------------------------
    async def _receive_loop(self):
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                    await self._dispatch(msg)
                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    logger.error(f"Gemini Live dispatch error: {e}")
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"Gemini Live connection closed: code={e.code}, reason='{e.reason}'")
        except Exception as e:
            if self.connected:
                logger.error(f"Gemini Live receive error: {e}")
        finally:
            self.connected = False

    async def _dispatch(self, msg: dict):
        # Handle function calls (tool use) — comes at top level, not inside serverContent
        tool_call = msg.get("toolCall")
        if tool_call:
            for fc in tool_call.get("functionCalls", []):
                fn_name = fc.get("name")
                fn_args = fc.get("args", {})
                fn_id = fc.get("id", "")
                logger.info(f"Gemini Live tool call: {fn_name}({fn_args})")

                if fn_name == "end_interview":
                    reason = fn_args.get("reason", "ai_decided")
                    # Fire callback — returns True (accept), False (reject), or dict with rejection details
                    should_end = True
                    rejection_reason = "The interview is not finished yet. Continue asking questions and wait for the system to tell you when it is time to end."
                    if self._on_interview_end:
                        result = await self._on_interview_end(reason)
                        if result is False:
                            should_end = False
                        elif isinstance(result, dict):
                            should_end = False
                            rejection_reason = result.get("reason", rejection_reason)
                    if should_end:
                        await self._send_function_response(fn_id, fn_name, {"status": "ok"})
                    else:
                        await self._send_function_response(fn_id, fn_name, {
                            "status": "rejected",
                            "reason": rejection_reason,
                        })
                else:
                    # Unknown function — respond with error
                    await self._send_function_response(fn_id, fn_name, {"error": "unknown_function"})
            return

        sc = msg.get("serverContent")
        if not sc:
            return

        mt = sc.get("modelTurn")
        if mt:
            for part in mt.get("parts", []):
                # Audio chunk
                inline = part.get("inlineData")
                if inline and inline.get("data"):
                    if self._on_audio:
                        await self._on_audio(inline["data"])

                # Text (transcript of AI speech — from modelTurn parts)
                text = part.get("text")
                if text:
                    self.ai_text_parts.append(text)
                    if self._on_text:
                        await self._on_text(text)

        # Input transcription (what the user said)
        input_tr = sc.get("inputTranscription")
        if input_tr and input_tr.get("text"):
            if self._on_input_transcription:
                await self._on_input_transcription(input_tr["text"])

        # Output transcription (what the AI said — separate from modelTurn text)
        output_tr = sc.get("outputTranscription")
        if output_tr and output_tr.get("text"):
            if self._on_output_transcription:
                await self._on_output_transcription(output_tr["text"])

        if sc.get("turnComplete"):
            if self._on_turn_complete:
                await self._on_turn_complete()

        if sc.get("interrupted"):
            logger.info("Gemini Live: model interrupted by user")
            if self._on_interrupted:
                await self._on_interrupted()

    # ------------------------------------------------------------------
    # Function response
    # ------------------------------------------------------------------
    async def _send_function_response(self, call_id: str, fn_name: str, result: dict):
        """Send a FunctionResponse back to Gemini after a tool call."""
        if not self.ws or not self.connected:
            return
        try:
            await self.ws.send(json.dumps({
                "toolResponse": {
                    "functionResponses": [{
                        "id": call_id,
                        "name": fn_name,
                        "response": result,
                    }]
                }
            }))
        except Exception as e:
            logger.error(f"Error sending function response: {e}")

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
        logger.info("Gemini Live session closed")
