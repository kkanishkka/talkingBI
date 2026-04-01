// src/components/FollowUpBar.jsx
import { useState } from "react";

export default function FollowUpBar({ onSubmit, disabled }) {
  const [text, setText] = useState("");

  const handleSubmit = () => {
    if (!text.trim() || disabled) return;
    onSubmit(text.trim());
    setText("");
  };

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="followup-bar">
      <span className="followup-label">Follow-up →</span>
      <input
        className="followup-input"
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKey}
        placeholder='e.g. "Now filter to age > 40" or "Show this as count instead"'
        disabled={disabled}
      />
      <button
        className="btn-followup"
        onClick={handleSubmit}
        disabled={disabled || !text.trim()}
      >
        Ask
      </button>
    </div>
  );
}