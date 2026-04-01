// src/components/AnalysisReport.jsx
function bold(text) {
  if (!text || typeof text !== "string") return text;
  return text.split(/\*\*(.*?)\*\*/g).map((p, i) =>
    i % 2 === 1 ? <strong key={i}>{p}</strong> : p
  );
}

const QTYPE_ICONS = {
  ranking:"🏆", comparison:"⚖️", trend:"📈",
  distribution:"📊", aggregation:"🔢", correlation:"🔗",
  filtered_lookup:"🔍", overview:"🗺️",
};

const METRIC_COLORS = {
  rate:"#3dd68c", count:"#4f8ef7", sum:"#f5a623",
  mean:"#9b7ff4", median:"#38bdf8", max:"#fb923c", min:"#a3e635",
};

export default function AnalysisReport({ report }) {
  if (!report) return null;
  const { query_intent = {}, plan_summary = {}, validation = {}, insight_report = {} } = report;

  const { valid, issues = [], warnings = [], quality_score = 0 } = validation;
  const { question_type = "analysis", metric = "count",
          primary_dimension, target_variable, assumptions = [] } = query_intent;
  const { headline, bullets = [], so_what, data_caveat } = insight_report;

  const icon  = QTYPE_ICONS[question_type] || "📊";
  const color = METRIC_COLORS[metric] || "#8b92a5";
  const qPct  = Math.round(quality_score * 100);
  const barColor = qPct > 70 ? "#3dd68c" : qPct > 40 ? "#f5a623" : "#f06060";

  if (!headline && !issues.length) return null;

  return (
    <section className="analysis-report">
      {/* header */}
      <div className="ar-header">
        <div className="ar-header-left">
          <span className="ar-qicon">{icon}</span>
          <div>
            <h3 className="ar-title">Query Analysis</h3>
            <p className="ar-subtitle">
              {question_type}
              {" · "}metric: <span className="ar-metric-badge" style={{ color }}>{metric}</span>
              {primary_dimension && <> · group by <code className="ar-code">{primary_dimension}</code></>}
              {target_variable   && <> · target <code className="ar-code">{target_variable}</code></>}
            </p>
          </div>
        </div>
        <div className="ar-quality">
          <span className="ar-quality-label">Quality</span>
          <div className="ar-quality-bar-wrap">
            <div className="ar-quality-bar-fill"
                 style={{ width: `${qPct}%`, background: barColor }} />
          </div>
          <span className="ar-quality-pct">{qPct}%</span>
        </div>
      </div>

      {/* blocking issues */}
      {issues.length > 0 && (
        <div className="ar-issues">
          {issues.map((iss, i) => (
            <div key={i} className="ar-issue"><span>✗</span>{iss}</div>
          ))}
        </div>
      )}

      {/* insight body */}
      {valid && headline && (
        <div className="ar-body">
          <p className="ar-headline">{bold(headline)}</p>

          {bullets.length > 0 && (
            <ul className="ar-bullets">
              {bullets.map((b, i) => (
                <li key={i} className="ar-bullet">
                  <span className="ar-bullet-dot" />
                  <span>{bold(b)}</span>
                </li>
              ))}
            </ul>
          )}

          {so_what && (
            <div className="ar-so-what">
              <span className="ar-so-what-label">Recommendation</span>
              <p>{bold(so_what)}</p>
            </div>
          )}

          {data_caveat && <p className="ar-caveat">{bold(data_caveat)}</p>}
        </div>
      )}

      {/* non-blocking warnings */}
      {warnings.length > 0 && (
        <div className="ar-warnings">
          {warnings.map((w, i) => (
            <div key={i} className="ar-warning"><span>⚠</span>{w}</div>
          ))}
        </div>
      )}

      {/* collapsible: how interpreted */}
      {(assumptions.length > 0 || plan_summary?.reasoning) && (
        <details className="ar-reasoning">
          <summary>How this query was interpreted</summary>
          {assumptions.map((a, i) => <p key={i}>{a}</p>)}
          {plan_summary?.reasoning && <p>{plan_summary.reasoning}</p>}
          {plan_summary?.formula_spec && (
            <p style={{ marginTop: 6 }}>
              <strong>Formula:</strong> {plan_summary.formula_spec}
            </p>
          )}
        </details>
      )}
    </section>
  );
}