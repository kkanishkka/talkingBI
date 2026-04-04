// components/ChatInput.jsx
// Textarea + send button for the chat interface.
// Supports Enter to submit (Shift+Enter for newline).

import { useState } from "react";

export default function ChatInput({ onSend, disabled, placeholder }) {
  const [value, setValue] = useState("");

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  return (
    <div className="chat-input-row">
      <textarea
        className="chat-input-textarea"
        rows={2}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder || "Ask a question about your data…"}
        disabled={disabled}
      />
      <button
        className="chat-send-btn"
        onClick={submit}
        disabled={disabled || !value.trim()}
        aria-label="Send"
      >
        {disabled ? (
          <span className="send-spinner" />
        ) : (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
          </svg>
        )}
      </button>
    </div>
  );
}