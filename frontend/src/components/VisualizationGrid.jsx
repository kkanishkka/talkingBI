// src/components/VisualizationGrid.jsx
// Renders a responsive grid of charts from the visualizations[] config.
// 100% driven by { chart_type, x_field, y_field, label_field, value_field, data }.
// Zero hardcoded column names.

import ChartPanel from "./ChartPanel";

export default function VisualizationGrid({ visualizations = [] }) {
  if (!visualizations.length) return null;

  return (
    <section>
      <h3 className="section-heading">
        <span className="section-icon">📊</span> Visualizations
      </h3>
      <div className="viz-grid">
        {visualizations.map((viz, i) => (
          <ChartPanel key={i} viz={viz} />
        ))}
      </div>
    </section>
  );
}