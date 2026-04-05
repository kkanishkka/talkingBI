// src/components/VoiceMicButton.jsx
// Voice recording button that:
//   1. Records audio via MediaRecorder API (webm/wav)
//   2. Sends audio file to POST /voice/query
//   3. Plays back TTS response audio automatically
//   4. Fires onResult(response) with full pipeline JSON
//
// Props:
//   sessionId: string   — required, active session
//   onResult:  fn(data) — called with voice response JSON
//   onError:   fn(msg)  — called on failure
//   disabled:  bool

import { useState, useRef, useCallback } from "react";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Supported MIME types in preference order
const MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

function getSupportedMimeType() {
  for (const mime of MIME_TYPES) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(mime)) {
      return mime;
    }
  }
  return "audio/webm";
}

function getFileExtension(mimeType) {
  if (mimeType.includes("ogg")) return "ogg";
  if (mimeType.includes("mp4")) return "m4a";
  return "webm";
}

export default function VoiceMicButton({ sessionId, onResult, onError, disabled }) {
  const [state, setState] = useState("idle"); // idle | recording | processing
  const mediaRecorderRef  = useRef(null);
  const chunksRef         = useRef([]);
  const audioRef          = useRef(null);

  const startRecording = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      onError?.("Microphone not available in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = getSupportedMimeType();
      const recorder = new MediaRecorder(stream, { mimeType });
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        // Stop all tracks
        stream.getTracks().forEach((t) => t.stop());

        const blob = new Blob(chunksRef.current, { type: mimeType });
        await sendAudio(blob, mimeType);
      };

      recorder.start(250); // collect chunks every 250ms
      mediaRecorderRef.current = recorder;
      setState("recording");
    } catch (err) {
      onError?.(`Microphone access denied: ${err.message}`);
    }
  }, [sessionId]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
      setState("processing");
    }
  }, []);

  const sendAudio = useCallback(async (blob, mimeType) => {
    try {
      const ext      = getFileExtension(mimeType);
      const formData = new FormData();
      formData.append("audio",      blob, `recording.${ext}`);
      formData.append("session_id", sessionId);

      const response = await fetch(`${BASE_URL}/voice/query`, {
        method: "POST",
        body:   formData,
      });

      if (!response.ok) {
        const j = await response.json().catch(() => ({}));
        throw new Error(j.detail || `Request failed (${response.status})`);
      }

      const data = await response.json();

      // Play TTS audio if available
      if (data.audio_b64 && data.audio_format) {
        playAudio(data.audio_b64, data.audio_format);
      }

      onResult?.(data);
    } catch (err) {
      onError?.(err.message || "Voice query failed.");
    } finally {
      setState("idle");
    }
  }, [sessionId, onResult, onError]);

  function playAudio(b64, format) {
    try {
      const binary   = atob(b64);
      const bytes    = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const blob     = new Blob([bytes], { type: `audio/${format}` });
      const url      = URL.createObjectURL(blob);
      if (audioRef.current) {
        audioRef.current.pause();
        URL.revokeObjectURL(audioRef.current.src);
      }
      const audio    = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => URL.revokeObjectURL(url);
      audio.play().catch(console.warn);
    } catch (err) {
      console.warn("TTS playback failed:", err);
    }
  }

  function handleClick() {
    if (disabled || state === "processing") return;
    if (state === "recording") {
      stopRecording();
    } else {
      startRecording();
    }
  }

  const isRecording   = state === "recording";
  const isProcessing  = state === "processing";

  return (
    <button
      className={`voice-mic-btn ${isRecording ? "recording" : ""} ${isProcessing ? "processing" : ""}`}
      onClick={handleClick}
      disabled={disabled || isProcessing}
      title={
        isRecording   ? "Click to stop recording"
        : isProcessing ? "Processing…"
        : "Click to speak"
      }
      aria-label={isRecording ? "Stop recording" : "Start voice query"}
    >
      {isProcessing ? (
        <span className="mic-spinner" />
      ) : isRecording ? (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          {/* Stop icon */}
          <rect x="6" y="6" width="12" height="12" rx="2" />
        </svg>
      ) : (
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          {/* Mic icon */}
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2H3v2a9 9 0 0 0 8 8.94V23h2v-2.06A9 9 0 0 0 21 12v-2h-2z"/>
        </svg>
      )}
      {isRecording && <span className="recording-pulse" />}
    </button>
  );
}