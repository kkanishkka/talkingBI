const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function handleResponse(response) {
  if (!response.ok) {
    let detail = "Request failed";
    try {
      const j = await response.json();
      detail = j.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return response.json();
}

export async function connectDatabase(connectionString) {
  const response = await fetch(`${BASE_URL}/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ connection_string: connectionString }),
  });
  return handleResponse(response);
}

export async function selectTable(sessionId, tableName) {
  const response = await fetch(`${BASE_URL}/select-table`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      table_name: tableName,
    }),
  });
  return handleResponse(response);
}

export async function askQuestion(sessionId, prompt) {
  const response = await fetch(`${BASE_URL}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      prompt,
    }),
  });
  return handleResponse(response);
}