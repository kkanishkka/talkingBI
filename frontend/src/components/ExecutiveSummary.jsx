// src/components/ExecutiveSummary.jsx
// Renders the AI-generated executive summary bullets at the top of the dashboard.
// Supports **bold** markdown syntax in bullet text.

/**
 * Parses a string with **bold** markers into React nodes.
 * e.g. "Dataset contains **1,200 records**" → "Dataset contains " + <strong>1,200 records</strong>
 */
function parseBold(text) {
  if (!text || typeof text !== "string") return text;
  const parts = text.split(/\*\*(.*?)\*\*/g);
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : part
  );
}

export default function ExecutiveSummary({ bullets = [] }) {
  if (!bullets.length) return null;

  return (
    <section className="exec-summary">
      <div className="exec-summary-header">
        <span className="exec-badge">Executive Summary</span>
        <span className="exec-title">Key Takeaways</span>
      </div>

      <ul className="exec-bullets">
        {bullets.map((bullet, i) => (
          <li key={i} className="exec-bullet">
            <span className="exec-bullet-dot" />
            <span>{parseBold(bullet)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}