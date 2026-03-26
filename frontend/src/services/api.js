// src/services/api.js
// API service layer for TalkingBI.
// All backend calls go through these functions — update BASE_URL for production.

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

/**
 * POST /dashboard
 * Sends a file + optional prompt and returns the full dashboard payload.
 *
 * @param {File}   file    - CSV or Excel file
 * @param {string} prompt  - Natural language prompt (optional)
 * @returns {Promise<DashboardResponse>}
 */
export async function generateDashboard(file, prompt = "") {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("prompt", prompt || "Give me a complete overview dashboard");

  const response = await fetch(`${BASE_URL}/dashboard`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    let detail = `Server error (${response.status})`;
    try {
      const json = await response.json();
      detail = json.detail || detail;
    } catch (_) {
      // ignore parse error, use default message
    }
    throw new Error(detail);
  }

  return response.json();
}

/**
 * POST /upload
 * Uploads a file and returns its schema profile + preview rows.
 */
export async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${BASE_URL}/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const json = await response.json().catch(() => ({}));
    throw new Error(json.detail || "Upload failed");
  }

  return response.json();
}