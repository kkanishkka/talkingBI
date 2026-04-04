// src/components/ChartPanel.jsx
// Wrapper around DynamicChart.
// Renders the chart title, why_this_chart rationale, formula_spec,
// and the chart itself. Also handles the "table" widget type cleanly.

import DynamicChart from "./DynamicChart";

export default function ChartPanel({ viz }) {
  if (!viz) return null;

  const {
    title,
    why_this_chart,
    formula_spec,
    chart_type,
    confidence,
    annotations = [],
  } = viz;

  const isKpi   = chart_type === "kpi_card";
  const isTable = chart_type === "table";

  return (
    <div className={`chart-panel ${isKpi ? "chart-panel--kpi" : ""} ${isTable ? "chart-panel--table" : ""}`}>

      {/* Header */}
      <div className="chart-header">
        <h4 className="chart-title">{title}</h4>
        {confidence != null && !isKpi && (
          <span className="chart-confidence" title="Analysis confidence">
            {Math.round(confidence * 100)}%
          </span>
        )}
      </div>

      {/* Chart / KPI / Table */}
      <div className="chart-body">
        <DynamicChart viz={viz} />
      </div>

      {/* Annotations (top-3 values for bar/horizontal_bar) */}
      {annotations.length > 0 && !isKpi && !isTable && (
        <div className="chart-annotations">
          {annotations.map((a, i) => (
            <span key={i} className="chart-annotation">{a}</span>
          ))}
        </div>
      )}

      {/* Footer: formula + chart rationale */}
      {(formula_spec || why_this_chart) && (
        <div className="chart-footer">
          {formula_spec && (
            <span className="chart-formula" title="How it was computed">
              📐 {formula_spec}
            </span>
          )}
          {why_this_chart && (
            <span className="chart-why" title="Why this chart type">
              💡 {why_this_chart}
            </span>
          )}
        </div>
      )}
    </div>
  );
}