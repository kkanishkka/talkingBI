// src/components/InsightCard.jsx
// Renders a single data insight with priority border, bold-text support,
// evidence field tags, and a visual confidence bar.

/**
 * Parses **bold** markers into React strong nodes.
 */
function parseBold(text) {
  if (!text || typeof text !== "string") return text;
  const parts = text.split(/\*\*(.*?)\*\*/g);
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : part
  );
}

const CATEGORY_LABELS = {
  distribution:  "Distribution",
  descriptive:   "Descriptive",
  trend:         "Trend",
  data_quality:  "Data Quality",
  structural:    "Structure",
  relationship:  "Relationship",
};

export default function InsightCard({ insight }) {
  if (!insight) return null;

  const {
    title = "Insight",
    insight_text = "",
    category = "descriptive",
    priority = "medium",
    evidence_fields = [],
    confidence = 0.75,
  } = insight;

  const categoryLabel = CATEGORY_LABELS[category] || category;
  const confPct = Math.round((confidence || 0.75) * 100);

  return (
    <div className={`insight-card priority-${priority}`}>
      {/* header row */}
      <div className="insight-card-header">
        <span className="insight-title">{title}</span>
        <div className="insight-meta">
          <span className="priority-pill">{priority}</span>
          <span className="insight-category">{categoryLabel}</span>
        </div>
      </div>

      {/* insight text with bold support */}
      <p className="insight-text">{parseBold(insight_text)}</p>

      {/* evidence fields */}
      {evidence_fields.length > 0 && (
        <div className="insight-evidence">
          {evidence_fields.map((f) => (
            <span key={f} className="evidence-tag">{f}</span>
          ))}
        </div>
      )}

      {/* confidence bar */}
      <div className="insight-confidence">
        Confidence: {confPct}%
        <span className="conf-bar">
          <span
            className="conf-fill"
            style={{ width: `${confPct}%` }}
          />
        </span>
      </div>
    </div>
  );
}