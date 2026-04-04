// components/MessageBubble.jsx
// Renders a single chat message — either user or assistant.
// Assistant messages include metadata (query resolved, turn count).

export default function MessageBubble({ message }) {
  const isUser = message.role === "user";

  return (
    <div className={`message-row ${isUser ? "user" : "assistant"}`}>
      <div className={`message-bubble ${isUser ? "user" : "assistant"}`}>
        {/* Main text */}
        <p className="message-text">{message.text}</p>

        {/* Assistant extras */}
        {!isUser && message.resolvedPrompt && message.wasFollowup && (
          <div className="message-resolved">
            <span className="resolved-label">Resolved query:</span>
            <span className="resolved-text">"{message.resolvedPrompt}"</span>
          </div>
        )}

        {!isUser && message.executedQuery && (
          <div className="message-meta">
            {message.executedQuery.question_type && (
              <span className="meta-chip intent">
                {message.executedQuery.question_type}
              </span>
            )}
            {message.executedQuery.dimension && (
              <span className="meta-chip dim">
                by {message.executedQuery.dimension}
              </span>
            )}
            {message.executedQuery.row_count != null && (
              <span className="meta-chip rows">
                {message.executedQuery.row_count} rows
              </span>
            )}
          </div>
        )}

        {/* Timestamp */}
        <span className="message-time">
          {new Date(message.timestamp).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
    </div>
  );
}