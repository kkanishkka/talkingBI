// src/components/ChartPanel.jsx
// Wraps DynamicChart with a header (title + type badge) and a why-this-chart footnote.
// All field resolution is delegated to DynamicChart — nothing is hardcoded here.

import DynamicChart from "./DynamicChart";

export default function ChartPanel({ viz }) {
  if (!viz) return null;

  const {
    title = "Chart",
    chart_type = "bar",
    why_this_chart = "",
  } = viz;

  return (
    <div className="chart-panel">
      {/* header */}
      <div className="chart-panel-header">
        <span className="chart-title">{title}</span>
        <span className="chart-type-badge">{chart_type}</span>
      </div>

      {/* chart body */}
      <div className="chart-body">
        <DynamicChart viz={viz} />
      </div>

      {/* rationale footnote */}
      {why_this_chart && (
        <p className="chart-why">{why_this_chart}</p>
      )}
    </div>
  );
}