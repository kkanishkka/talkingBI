// src/components/InsightCard.jsx
function bold(text) {
  if (!text || typeof text !== "string") return text;
  return text.split(/\*\*(.*?)\*\*/g).map((p, i) =>
    i % 2 === 1 ? <strong key={i}>{p}</strong> : p
  );
}

const CAT_LABELS = {
  distribution:"Distribution", descriptive:"Descriptive",
  diagnostic:"Diagnostic", prescriptive:"Prescriptive",
  data_quality:"Data Quality", structural:"Structure",
  trend:"Trend", evaluative:"Evaluative",
};

export default function InsightCard({ insight }) {
  if (!insight) return null;
  const {
    title="Insight", insight_text="", category="descriptive",
    priority="medium", evidence_fields=[], confidence=0.75,
  } = insight;

  const confPct = Math.round((confidence||0.75)*100);

  return (
    <div className={`insight-card priority-${priority}`}>
      <div className="insight-card-header">
        <span className="insight-title">{title}</span>
        <div className="insight-meta">
          <span className="priority-pill">{priority}</span>
          <span className="insight-category">{CAT_LABELS[category]||category}</span>
        </div>
      </div>
      <p className="insight-text">{bold(insight_text)}</p>
      {evidence_fields.length > 0 && (
        <div className="insight-evidence">
          {evidence_fields.map(f=>(
            <span key={f} className="evidence-tag">{f}</span>
          ))}
        </div>
      )}
      <div className="insight-confidence">
        Confidence: {confPct}%
        <span className="conf-bar">
          <span className="conf-fill" style={{width:`${confPct}%`}}/>
        </span>
      </div>
    </div>
  );
}