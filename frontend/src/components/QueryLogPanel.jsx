function prettyValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderFilter(filter, index) {
  return (
    <div key={index} className="ql-filter-chip">
      <code>{filter.column}</code>
      <span>{filter.operator}</span>
      <strong>{prettyValue(filter.value)}</strong>
    </div>
  );
}

function renderOperation(op, index) {
  return (
    <div key={index} className="ql-op-row">
      <div className="ql-op-step">{op.step ?? index + 1}</div>
      <div className="ql-op-body">
        <div className="ql-op-name">{op.op}</div>
        <pre className="ql-op-args">{JSON.stringify(op.args || {}, null, 2)}</pre>
      </div>
    </div>
  );
}

export default function QueryLogPanel({ executedQuery }) {
  if (!executedQuery) return null;

  const {
    query_type,
    metric,
    question_type,
    dimension,
    secondary_dimension,
    target_variable,
    filters = [],
    formula,
    operations = [],
    row_count,
  } = executedQuery;

  return (
    <section className="query-log-panel">
      <div className="query-log-header">
        <div>
          <h3 className="query-log-title">How this was computed</h3>
          <p className="query-log-subtitle">
            Transparent execution details for the current dashboard query
          </p>
        </div>
        <span className="query-type-badge">{query_type || "pandas"}</span>
      </div>

      <div className="query-log-meta">
        <div className="ql-meta-item">
          <span className="ql-label">Question type</span>
          <span className="ql-value">{prettyValue(question_type)}</span>
        </div>
        <div className="ql-meta-item">
          <span className="ql-label">Metric</span>
          <span className="ql-value">{prettyValue(metric)}</span>
        </div>
        <div className="ql-meta-item">
          <span className="ql-label">Primary dimension</span>
          <span className="ql-value">{prettyValue(dimension)}</span>
        </div>
        <div className="ql-meta-item">
          <span className="ql-label">Secondary dimension</span>
          <span className="ql-value">{prettyValue(secondary_dimension)}</span>
        </div>
        <div className="ql-meta-item">
          <span className="ql-label">Target variable</span>
          <span className="ql-value">{prettyValue(target_variable)}</span>
        </div>
        <div className="ql-meta-item">
          <span className="ql-label">Result rows</span>
          <span className="ql-value">{prettyValue(row_count)}</span>
        </div>
      </div>

      <div className="ql-block">
        <span className="ql-block-label">Formula</span>
        <div className="ql-formula">{prettyValue(formula)}</div>
      </div>

      <div className="ql-block">
        <span className="ql-block-label">Filters</span>
        {filters.length > 0 ? (
          <div className="ql-filters">
            {filters.map(renderFilter)}
          </div>
        ) : (
          <div className="ql-empty">No filters applied</div>
        )}
      </div>

      <details className="ql-details">
        <summary>Execution steps ({operations.length})</summary>
        {operations.length > 0 ? (
          <div className="ql-ops-list">
            {operations.map(renderOperation)}
          </div>
        ) : (
          <div className="ql-empty">No execution steps available</div>
        )}
      </details>
    </section>
  );
}