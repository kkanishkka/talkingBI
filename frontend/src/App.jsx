// src/App.jsx
import { useState, useCallback } from "react";
import FileUpload        from "./components/FileUpload";
import PromptBar         from "./components/PromptBar";
import ExecutiveSummary  from "./components/ExecutiveSummary";
import DatasetProfile    from "./components/DatasetProfile";
import VisualizationGrid from "./components/VisualizationGrid";
import InsightCard       from "./components/InsightCard";
import AnalysisReport    from "./components/AnalysisReport";
import AssumptionBlock   from "./components/AssumptionBlock";
import KPICoverage       from "./components/KPICoverage";
import LayoutSwitcher    from "./components/LayoutSwitcher";
import FollowUpBar       from "./components/FollowUpBar";
import LoadingSpinner    from "./components/LoadingSpinner";
import { generateDashboard } from "./services/api";
import "./App.css";

export default function App() {
  const [file,          setFile]          = useState(null);
  const [prompt,        setPrompt]        = useState("");
  const [data,          setData]          = useState(null);
  const [sessionId,     setSessionId]     = useState("");
  const [loading,       setLoading]       = useState(false);
  const [error,         setError]         = useState(null);
  const [activeLayout,  setActiveLayout]  = useState(0);

  const runQuery = useCallback(async (queryPrompt, queryFile, sid) => {
    setLoading(true);
    setError(null);
    try {
      const result = await generateDashboard(queryFile, queryPrompt, sid);
      setData(result);
      setSessionId(result.session_id || "");
      setActiveLayout(0);
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleGenerate  = ()  => file && runQuery(prompt, file, "");
  const handleFollowUp  = (q) => file && q.trim() && runQuery(q, file, sessionId);
  const handleReset     = ()  => {
    setFile(null); setPrompt(""); setData(null);
    setSessionId(""); setError(null); setActiveLayout(0);
  };

  const hasAnalysis = Boolean(data?.analysis_report?.insight_report?.headline);
  const hasLayouts  = data?.layouts?.length > 0;

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="header-brand">
            <span className="brand-icon">◈</span>
            <span className="brand-name">TalkingBI</span>
          </div>
          <p className="header-tagline">AI-Powered Business Intelligence</p>
          {sessionId && (
            <span className="session-badge" title={`Session: ${sessionId}`}>
              ● Session active
            </span>
          )}
        </div>
      </header>

      <main className="app-main">
        {!data && !loading && (
          <section className="upload-section">
            <div className="upload-card">
              <h2 className="upload-title">Ask your data a question</h2>
              <p className="upload-subtitle">
                Upload any CSV or Excel file. Type a business question.
                TalkingBI plans the analysis, executes it, and explains what it found.
              </p>
              <FileUpload file={file} onFileChange={setFile} />
              <PromptBar
                prompt={prompt}
                onPromptChange={setPrompt}
                onGenerate={handleGenerate}
                disabled={!file || loading}
              />
              {error && <ErrorBanner message={error} />}
            </div>
          </section>
        )}

        {loading && <LoadingSpinner />}

        {data && !loading && (
          <div className="dashboard-output">
            {/* ── Topbar ── */}
            <div className="dashboard-topbar">
              <div className="topbar-left">
                <span className="dash-icon">◈</span>
                <h2 className="dash-title">Dashboard</h2>
                {data.dataset_profile && (
                  <span className="dash-meta">
                    {data.dataset_profile.rows?.toLocaleString()} rows ·{" "}
                    {data.dataset_profile.columns} columns
                  </span>
                )}
              </div>
              <div className="topbar-right">
                {hasLayouts && (
                  <LayoutSwitcher
                    layouts={data.layouts}
                    active={activeLayout}
                    onChange={setActiveLayout}
                  />
                )}
                <button className="btn-reset" onClick={handleReset}>
                  ← New Dataset
                </button>
              </div>
            </div>

            {/* ── Warnings ── */}
            {data.warnings?.length > 0 && (
              <div className="warnings-strip">
                {data.warnings.map((w, i) => (
                  <div key={i} className="warning-item">⚠ {w}</div>
                ))}
              </div>
            )}

            {/* ── Primary: query answer ── */}
            {hasAnalysis && (
              <AnalysisReport report={data.analysis_report} />
            )}

            {/* ── Assumptions + KPI Coverage ── */}
            {(data.assumptions?.formula_spec || data.kpi_coverage) && (
              <div className="meta-row">
                {data.assumptions?.formula_spec && (
                  <AssumptionBlock assumptions={data.assumptions} />
                )}
                {data.kpi_coverage && (
                  <KPICoverage coverage={data.kpi_coverage} />
                )}
              </div>
            )}

            {/* ── Visualizations ── */}
            {data.visualizations?.length > 0 && (
              <VisualizationGrid
                visualizations={data.visualizations}
                layout={data.layouts?.[activeLayout] ?? null}
              />
            )}

            {/* ── Follow-up query ── */}
            {file && (
              <FollowUpBar onSubmit={handleFollowUp} disabled={loading} />
            )}

            {/* ── Dataset context (below fold) ── */}
            {data.executive_summary?.length > 0 && (
              <ExecutiveSummary bullets={data.executive_summary} />
            )}

            {data.dataset_insights?.length > 0 && (
              <section className="insights-section">
                <h3 className="section-heading">
                  <span className="section-icon">🔍</span> Dataset Insights
                </h3>
                <div className="insights-grid">
                  {data.dataset_insights.map((ins, i) => (
                    <InsightCard key={i} insight={ins} />
                  ))}
                </div>
              </section>
            )}

            {data.dataset_profile && (
              <DatasetProfile profile={data.dataset_profile} />
            )}

            {error && <ErrorBanner message={error} />}
          </div>
        )}
      </main>
    </div>
  );
}

function ErrorBanner({ message }) {
  return (
    <div className="error-banner" role="alert">
      <span className="error-icon">⚠</span>
      <span>{message}</span>
    </div>
  );
}