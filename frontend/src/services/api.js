// src/services/api.js — TalkingBI v5
const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function handleResponse(response) {
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const j = await response.json(); detail = j.detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

// Database
export async function connectDatabase(connectionString) {
  return handleResponse(await fetch(`${BASE_URL}/connect`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connection_string: connectionString }),
  }));
}

export async function selectTable(sessionId, tableName) {
  return handleResponse(await fetch(`${BASE_URL}/select-table`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, table_name: tableName }),
  }));
}

// Text queries
export async function askQuestion(sessionId, prompt) {
  return handleResponse(await fetch(`${BASE_URL}/ask`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, prompt }),
  }));
}

export async function chatQuery(sessionId, message) {
  return handleResponse(await fetch(`${BASE_URL}/chat`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  }));
}

/**
 * Voice query — multipart form upload.
 * @param {string} sessionId
 * @param {Blob}   audioBlob   recorded audio (webm/wav/mp3)
 * @param {string} filename    e.g. "recording.webm"
 */
export async function voiceQuery(sessionId, audioBlob, filename = "recording.webm") {
  const formData = new FormData();
  formData.append("audio",      audioBlob, filename);
  formData.append("session_id", sessionId);
  return handleResponse(await fetch(`${BASE_URL}/voice/query`, {
    method: "POST", body: formData,
  }));
}

// Session management
export async function getSession(sessionId) {
  return handleResponse(await fetch(`${BASE_URL}/session/${sessionId}`));
}

export async function getSessionHistory(sessionId) {
  return handleResponse(await fetch(`${BASE_URL}/session/${sessionId}/history`));
}

export async function deleteSession(sessionId) {
  return handleResponse(await fetch(`${BASE_URL}/session/${sessionId}`, { method: "DELETE" }));
}