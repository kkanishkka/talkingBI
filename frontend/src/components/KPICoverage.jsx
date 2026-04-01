// src/components/KPICoverage.jsx
export default function KPICoverage({ coverage }) {
  if (!coverage) return null;

  const {
    coverage_pct    = 100,
    coverage_note   = "",
    requested_kpis  = [],
    covered_kpis    = [],
    uncovered_kpis  = [],
  } = coverage;

  if (requested_kpis.length === 0) return null;

  const pctClass = coverage_pct >= 80 ? "good" : coverage_pct >= 50 ? "warn" : "bad";
  const barColor = coverage_pct >= 80 ? "#3dd68c" : coverage_pct >= 50 ? "#f5a623" : "#f06060";

  return (
    <div className="kpi-coverage">
      <div className="kpi-coverage-header">
        <span className="kpi-coverage-title">KPI Coverage</span>
        <span className={`kpi-pct ${pctClass}`}>{coverage_pct}%</span>
      </div>

      <div className="kpi-bar-wrap">
        <div className="kpi-bar-fill"
             style={{ width: `${coverage_pct}%`, background: barColor }} />
      </div>

      {coverage_note && (
        <p className="kpi-note">{coverage_note}</p>
      )}

      {(covered_kpis.length > 0 || uncovered_kpis.length > 0) && (
        <div className="kpi-lists">
          {covered_kpis.length > 0 && (
            <div className="kpi-list-col">
              <div className="kpi-list-label">Covered</div>
              {covered_kpis.map((k, i) => (
                <span key={i} className="kpi-tag covered">{k}</span>
              ))}
            </div>
          )}
          {uncovered_kpis.length > 0 && (
            <div className="kpi-list-col">
              <div className="kpi-list-label">Missing</div>
              {uncovered_kpis.map((k, i) => (
                <span key={i} className="kpi-tag uncovered">{k}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}