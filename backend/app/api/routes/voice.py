"""
app/api/routes/voice.py
══════════════════════════════════════════════════════════════════════
Voice Query Endpoint

Flow:
  POST /voice/query
    → receives audio file (wav/webm/mp3)
    → transcribes via Whisper (openai.audio.transcriptions)
    → sends transcribed text through the SAME pipeline as /chat
    → returns dashboard JSON  +  spoken TTS audio (base64)
    → frontend plays spoken answer back

Design decisions:
  1. STT: OpenAI Whisper API (same key as LLM client)
     Fallback: if no Whisper key, returns 503 with clear message
  2. TTS: OpenAI TTS API (model: tts-1, voice: alloy)
     Fallback: returns null audio_b64, frontend skips playback
  3. Both STT and TTS failures are non-fatal for the BI pipeline —
     the dashboard JSON is always returned even if audio fails
  4. Session is required — user must have already connected a DB
     and selected a table before using voice

Endpoint:
  POST /voice/query
    Form fields:
      audio:      UploadFile  (wav/webm/mp3/m4a/ogg)
      session_id: str
    Response:
      {
        "transcribed_text": str,
        "assistant_message": str,
        "audio_b64": str | null,   // base64 WAV/MP3 for playback
        "audio_format": "mp3" | null,
        "dashboard": { ... },      // full pipeline response
        "session_id": str
      }
══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import base64
import logging
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.core.exceptions import AmbiguityError, IngestionError
from app.core.session_store import session_store
from app.pipeline.orchestrator import run_pipeline_from_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


# ═══════════════════════════════════════════════════════════════════
# SECTION 1 — Speech-to-Text (Whisper)
# ═══════════════════════════════════════════════════════════════════

def _transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    """
    Transcribe audio bytes using OpenAI Whisper API.
    Returns the transcribed text string.
    Raises HTTPException(503) if Whisper is unavailable.
    Raises HTTPException(422) if transcription fails.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Voice transcription requires OPENAI_API_KEY. "
                   "Please set it in your environment.",
        )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        # Whisper requires a file-like object with a name
        suffix = _get_suffix(filename)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as f:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="text",
                )
            text = str(response).strip()
        finally:
            import os as _os
            _os.unlink(tmp_path)

        if not text:
            raise HTTPException(
                status_code=422,
                detail="Audio transcription returned empty text. "
                       "Please speak clearly and try again.",
            )

        logger.info("Voice STT: transcribed '%s...'", text[:60])
        return text

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Voice STT failed: %s", exc)
        raise HTTPException(
            status_code=422,
            detail=f"Audio transcription failed: {exc}",
        )


def _get_suffix(filename: str) -> str:
    """Extract file suffix for temp file."""
    if "." in filename:
        return "." + filename.rsplit(".", 1)[-1].lower()
    return ".wav"


# ═══════════════════════════════════════════════════════════════════
# SECTION 2 — Text-to-Speech (OpenAI TTS)
# ═══════════════════════════════════════════════════════════════════

def _synthesise_speech(text: str) -> Optional[tuple[bytes, str]]:
    """
    Convert text to speech using OpenAI TTS API.
    Returns (audio_bytes, "mp3") or None if unavailable/failed.

    Non-fatal: failures are logged but do not break the voice endpoint.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.debug("TTS: no API key, skipping speech synthesis")
        return None

    # Truncate very long responses to avoid TTS cost/latency
    tts_text = text[:500] if len(text) > 500 else text

    try:
        from openai import OpenAI
        client   = OpenAI(api_key=api_key)
        voice    = os.getenv("TTS_VOICE", "alloy")   # alloy|echo|fable|onyx|nova|shimmer
        tts_model = os.getenv("TTS_MODEL", "tts-1")

        response = client.audio.speech.create(
            model=tts_model,
            voice=voice,
            input=tts_text,
            response_format="mp3",
        )
        audio_bytes = response.content
        logger.info("Voice TTS: synthesised %d bytes", len(audio_bytes))
        return audio_bytes, "mp3"

    except Exception as exc:
        logger.warning("Voice TTS failed (non-fatal): %s", exc)
        return None


# ═══════════════════════════════════════════════════════════════════
# SECTION 3 — helper: extract assistant message for TTS
# ═══════════════════════════════════════════════════════════════════

def _extract_speakable_answer(pipeline_response: dict) -> str:
    """
    Extract a short, speakable answer from the pipeline response.
    Priority: insight headline → plan result_label → generic.
    """
    report  = pipeline_response.get("analysis_report", {})
    insight = report.get("insight_report", {})

    headline = insight.get("headline", "")
    if headline:
        # Clean markdown bold markers for speech
        return headline.replace("**", "")

    plan = report.get("plan_summary", {})
    label = plan.get("result_label", "")
    if label:
        return f"Analysis complete: {label}."

    # KPI result
    vizs = pipeline_response.get("visualizations", [])
    if vizs and pipeline_response.get("is_kpi_only"):
        v = vizs[0]
        data = v.get("data", [])
        if data:
            row = data[0]
            return (
                f"{row.get('metric', 'Value')}: {row.get('value', 'N/A')}."
            )

    return "Your analysis is ready."


# ═══════════════════════════════════════════════════════════════════
# SECTION 4 — route
# ═══════════════════════════════════════════════════════════════════

@router.post("/query")
async def voice_query(
    audio:      UploadFile = File(..., description="Audio file: wav/webm/mp3/m4a/ogg"),
    session_id: str        = Form(..., description="Active session ID with table selected"),
):
    """
    Voice BI query endpoint.

    1. Transcribes audio → text (Whisper)
    2. Runs the same BI pipeline as /chat
    3. Synthesises the answer as speech (TTS)
    4. Returns dashboard JSON + base64 audio

    Session must already have a table selected (via /connect + /select-table).
    """
    session_id = session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required.")

    # ── Validate session ──────────────────────────────────────────
    ctx = session_store.get(session_id)
    if not ctx:
        raise HTTPException(
            status_code=404,
            detail="Session not found. Please connect to a database and select a table first.",
        )
    if not ctx.connection_string:
        raise HTTPException(
            status_code=400,
            detail="No database connected for this session.",
        )
    if not ctx.selected_table:
        raise HTTPException(
            status_code=400,
            detail="No table selected. Please select a table before using voice queries.",
        )

    # ── Read audio ────────────────────────────────────────────────
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Audio file is empty.")

    filename = audio.filename or "audio.wav"
    logger.info(
        "Voice query: session=%s file=%s size=%d bytes",
        session_id[:8], filename, len(audio_bytes),
    )

    # ── STT: audio → text ─────────────────────────────────────────
    transcribed_text = _transcribe_audio(audio_bytes, filename)

    # ── BI Pipeline ───────────────────────────────────────────────
    try:
        pipeline_response = run_pipeline_from_text(
            prompt=     transcribed_text,
            session_id= session_id,
        )
    except AmbiguityError as exc:
        # Speak the clarification question back
        clarification_question = exc.clarification.get("question", "Could you clarify your question?")
        tts_result = _synthesise_speech(clarification_question)
        audio_b64, audio_fmt = (
            (base64.b64encode(tts_result[0]).decode(), tts_result[1])
            if tts_result else (None, None)
        )
        return JSONResponse(
            status_code=200,
            content={
                "type":              "clarification",
                "session_id":        session_id,
                "transcribed_text":  transcribed_text,
                "needs_clarification": True,
                "clarification":     exc.clarification,
                "assistant_message": clarification_question,
                "audio_b64":         audio_b64,
                "audio_format":      audio_fmt,
            },
        )
    except IngestionError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.user_message)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Voice pipeline failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}")

    # ── TTS: answer → speech ──────────────────────────────────────
    assistant_message = _extract_speakable_answer(pipeline_response)
    tts_result        = _synthesise_speech(assistant_message)
    audio_b64: Optional[str] = None
    audio_fmt: Optional[str] = None
    if tts_result:
        audio_b64 = base64.b64encode(tts_result[0]).decode()
        audio_fmt = tts_result[1]

    return {
        "type":             "answer",
        "session_id":       session_id,
        "transcribed_text": transcribed_text,
        "assistant_message": assistant_message,
        "audio_b64":        audio_b64,
        "audio_format":     audio_fmt,

        # Full dashboard payload
        "dashboard":        pipeline_response,

        # Convenience shortcuts
        "visualizations":   pipeline_response.get("visualizations", []),
        "is_kpi_only":      pipeline_response.get("is_kpi_only", False),
        "executed_query":   pipeline_response.get("executed_query", {}),
        "warnings":         pipeline_response.get("warnings", []),
    }