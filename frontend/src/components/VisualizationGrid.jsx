// src/components/VisualizationGrid.jsx
// v2: handles mixed widget types (chart, table, kpi_card)
// Skips layout cells that point to KPI-only vizs already shown
// in DashboardWorkspace.

import ChartPanel from "./ChartPanel";

export default function VisualizationGrid({ visualizations = [], layout = null }) {
  if (!visualizations.length) return null;

  return (
    <section className="viz-section">
      <h3 className="section-heading">
        <span className="section-icon">📊</span> Visualizations
        {layout && (
          <span className="section-layout-name">— {layout.layout_name}</span>
        )}
      </h3>

      {layout?.cells?.length > 0 ? (
        <div className="viz-grid-layout">
          {layout.cells.map((cell, i) => {
            const viz = visualizations[cell.viz_index];
            if (!viz) return null;
            return (
              <div
                key={i}
                className={`viz-cell viz-cell--${viz.chart_type || "chart"}`}
                style={{
                  gridColumn: `${cell.col_start} / span ${cell.col_span}`,
                  gridRow:    `span ${cell.row_span || 1}`,
                }}
              >
                <ChartPanel viz={viz} />
              </div>
            );
          })}
        </div>
      ) : (
        <div className="viz-grid">
          {visualizations.map((viz, i) => (
            <ChartPanel key={i} viz={viz} />
          ))}
        </div>
      )}
    </section>
  );
}