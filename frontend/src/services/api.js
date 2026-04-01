// src/services/api.js
const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function _handleResponse(response) {
  if (!response.ok) {
    let detail = `Server error (${response.status})`;
    try { const j = await response.json(); detail = j.detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

export async function generateDashboard(file, prompt = "", sessionId = "") {
  const form = new FormData();
  form.append("file",       file);
  form.append("prompt",     prompt || "Give me a complete overview dashboard");
  form.append("session_id", sessionId);
  return _handleResponse(await fetch(`${BASE_URL}/dashboard`, { method: "POST", body: form }));
}

export async function uploadFile(file) {
  const form = new FormData();
  form.append("file", file);
  return _handleResponse(await fetch(`${BASE_URL}/upload`, { method: "POST", body: form }));
}