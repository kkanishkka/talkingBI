// components/SuggestedQuestions.jsx
// Clickable suggestion chips shown below the dashboard.
// Clicking a chip fires it as the next query.

export default function SuggestedQuestions({ suggestions, onSelect, disabled }) {
  if (!suggestions || suggestions.length === 0) return null;

  return (
    <div className="suggestions-container">
      <p className="suggestions-label">Try next:</p>
      <div className="suggestions-chips">
        {suggestions.map((s, i) => (
          <button
            key={i}
            className="suggestion-chip"
            onClick={() => onSelect(s)}
            disabled={disabled}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}