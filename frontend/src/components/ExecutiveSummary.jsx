// src/components/ExecutiveSummary.jsx
export default function ExecutiveSummary({ summary }) {
  if (!summary) return null;
  return (
    <div className="exec-summary">
      <div className="exec-summary-label">◈ AI-Generated Summary</div>
      <p className="exec-summary-text">{summary}</p>
    </div>
  );
}