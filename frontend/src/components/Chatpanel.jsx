// components/ChatPanel.jsx
// Full scrollable conversation history panel.
// Renders a list of MessageBubble components.

import { useEffect, useRef } from "react";
import MessageBubble from "./MessageBubble";

export default function ChatPanel({ messages, loading }) {
  const bottomRef = useRef(null);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  return (
    <div className="chat-panel">
      {messages.length === 0 && (
        <div className="chat-empty-state">
          <div className="chat-empty-icon">💬</div>
          <p className="chat-empty-title">Ask your data anything</p>
          <p className="chat-empty-subtitle">
            Try: "Show top 5 categories by sales" or "Compare profit by region"
          </p>
        </div>
      )}

      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}

      {loading && (
        <div className="message-row assistant">
          <div className="message-bubble assistant thinking">
            <span className="thinking-dot" />
            <span className="thinking-dot" />
            <span className="thinking-dot" />
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}