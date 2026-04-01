// src/components/AssumptionBlock.jsx
// Shows every inference the backend made: formula, metric definition,
// grouping, filters, positive class. Answers "how did you compute this?"

export default function AssumptionBlock({ assumptions }) {
  if (!assumptions) return null;

  const {
    formula_spec       = "",
    metric_assumption  = "",
    dimension_assumption = "",
    filter_assumptions = [],
    positive_class     = null,
    can_correct        = true,
  } = assumptions;

  const hasContent = formula_spec || metric_assumption || dimension_assumption
                     || filter_assumptions.length > 0;
  if (!hasContent) return null;

  return (
    <div className="assumption-block">
      <div className="assumption-header">
        <span className="assumption-icon">🧮</span>
        <span className="assumption-title">How it was computed</span>
      </div>

      {formula_spec && (
        <div className="assumption-formula">{formula_spec}</div>
      )}

      <div className="assumption-rows">
        {metric_assumption && (
          <div className="assumption-row">
            <span className="assumption-label">Metric</span>
            <span className="assumption-value">{metric_assumption}</span>
          </div>
        )}

        {dimension_assumption && (
          <div className="assumption-row">
            <span className="assumption-label">Grouping</span>
            <span className="assumption-value">{dimension_assumption}</span>
          </div>
        )}

        {positive_class && (
          <div className="assumption-row">
            <span className="assumption-label">Positive class</span>
            <span className="positive-class">"{positive_class}"</span>
          </div>
        )}

        {filter_assumptions.map((f, i) => (
          <div key={i} className="assumption-row">
            <span className="assumption-label">Filter</span>
            <span className="assumption-value">{f}</span>
          </div>
        ))}
      </div>

      {can_correct && (
        <p className="assumption-note">
          If any assumption is incorrect, refine your query to override it.
        </p>
      )}
    </div>
  );
}