// src/components/DashboardWorkspace.jsx
// v3: proper KPI-only path — renders KPI card without chart area
// when is_kpi_only === true.

import ExecutiveSummary from "./ExecutiveSummary";
import AnalysisReport from "./AnalysisReport";
import VisualizationGrid from "./VisualizationGrid";
import AssumptionBlock from "./AssumptionBlock";
import DatasetProfile from "./DatasetProfile";
import SuggestedQuestions from "./SuggestedQuestions";
import DynamicChart from "./DynamicChart";

export default function DashboardWorkspace({ dashboard, onSuggestionClick, loading }) {
  if (!dashboard) {
    return (
      <div className="workspace-empty">
        <div className="workspace-empty-icon">📊</div>
        <p>Your dashboard will appear here once you ask a question.</p>
      </div>
    );
  }

  const d = dashboard.dashboard || dashboard;
  const hasClarification = d.needs_clarification || dashboard.needs_clarification;

  if (hasClarification) {
    const clarification = d.clarification || dashboard.clarification || {};
    return (
      <div className="workspace-clarification">
        <h3>🤔 Clarification needed</h3>
        <p>{d.message || dashboard.message}</p>
        {clarification.question && (
          <p className="clarification-question">{clarification.question}</p>
        )}
        {clarification.options?.length > 0 && (
          <div className="clarification-options">
            {clarification.options.map((opt, i) => (
              <button key={i} className="suggestion-chip"
                onClick={() => onSuggestionClick?.(opt)}>
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  const vizs        = d.visualizations || [];
  const layouts     = d.layouts || [];
  const execQuery   = d.executed_query || dashboard.executed_query || {};
  const suggestions = dashboard.follow_up_suggestions || d.follow_up_suggestions || [];
  const warnings    = d.warnings || [];
  const isKpiOnly   = d.is_kpi_only || dashboard.is_kpi_only || false;

  return (
    <div className="dashboard-workspace">

      {/* Query understanding banner */}
      {execQuery.question_type && (
        <div className="query-banner">
          <span className="query-banner-label">Analysis:</span>
          <span className={`query-banner-chip intent${isKpiOnly ? " kpi" : ""}`}>
            {isKpiOnly ? "KPI" : execQuery.question_type}
          </span>
          {execQuery.dimension && (
            <span className="query-banner-chip dim">by {execQuery.dimension}</span>
          )}
          {execQuery.target_variable && (
            <span className="query-banner-chip metric">{execQuery.target_variable}</span>
          )}
          {execQuery.row_count != null && !isKpiOnly && (
            <span className="query-banner-chip rows">{execQuery.row_count} rows</span>
          )}
          {execQuery.filters?.length > 0 && (
            <span className="query-banner-chip filter">
              🔍 {execQuery.filters.map(f => `${f.column} ${f.operator} ${f.value}`).join(", ")}
            </span>
          )}
        </div>
      )}

      {/* KPI-only path */}
      {isKpiOnly && vizs.length > 0 && (
        <div className="kpi-only-section">
          <DynamicChart viz={vizs[0]} />
          {execQuery.formula && (
            <div className="kpi-formula">
              <span className="formula-label">How it was computed: </span>
              <span className="formula-text">{execQuery.formula}</span>
            </div>
          )}
        </div>
      )}

      {/* Regular chart path */}
      {!isKpiOnly && d.analysis_report && (
        <AnalysisReport report={d.analysis_report} />
      )}

      {!isKpiOnly && vizs.length > 0 && layouts.length > 0 && (
        <VisualizationGrid visualizations={vizs} layout={layouts[0]} />
      )}

      {d.executive_summary?.length > 0 && (
        <ExecutiveSummary bullets={d.executive_summary} />
      )}

      {d.assumptions && Object.values(d.assumptions).some(v => v) && (
        <AssumptionBlock assumptions={d.assumptions} />
      )}

      {d.dataset_profile && <DatasetProfile profile={d.dataset_profile} />}

      {warnings.length > 0 && (
        <div className="dashboard-warnings">
          <h4>⚠ Warnings</h4>
          <ul>{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}

      <SuggestedQuestions
        suggestions={suggestions}
        onSelect={onSuggestionClick}
        disabled={loading}
      />
    </div>
  );
}