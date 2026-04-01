// src/components/ChartPanel.jsx
import DynamicChart from "./DynamicChart";

export default function ChartPanel({ viz }) {
  if (!viz) return null;
  const { title="Chart", chart_type="bar", why_this_chart="", is_primary=false, formula_spec="" } = viz;

  return (
    <div className={`chart-panel${is_primary ? " primary-chart" : ""}`}>
      <div className="chart-panel-header">
        <span className="chart-title">{title}</span>
        <div className="chart-badges">
          {is_primary && <span className="primary-badge">Primary</span>}
          <span className="chart-type-badge">{chart_type}</span>
        </div>
      </div>
      {formula_spec && <p className="chart-formula">{formula_spec}</p>}
      <div className="chart-body"><DynamicChart viz={viz} /></div>
      {why_this_chart && <p className="chart-why">{why_this_chart}</p>}
    </div>
  );
}