// src/components/ExecutiveSummary.jsx
function bold(text) {
  if (!text || typeof text !== "string") return text;
  return text.split(/\*\*(.*?)\*\*/g).map((p, i) =>
    i % 2 === 1 ? <strong key={i}>{p}</strong> : p
  );
}

export default function ExecutiveSummary({ bullets = [] }) {
  if (!bullets.length) return null;
  return (
    <section className="exec-summary">
      <div className="exec-summary-header">
        <span className="exec-badge">Executive Summary</span>
        <span className="exec-title">Dataset Overview</span>
      </div>
      <ul className="exec-bullets">
        {bullets.map((b, i) => (
          <li key={i} className="exec-bullet">
            <span className="exec-bullet-dot" />
            <span>{bold(b)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}