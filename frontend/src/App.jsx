// src/App.jsx — TalkingBI dynamic dashboard (improved)
import { useState } from "react";
import FileUpload        from "./components/FileUpload";
import PromptBar         from "./components/PromptBar";
import ExecutiveSummary  from "./components/ExecutiveSummary";
import DatasetProfile    from "./components/DatasetProfile";
import VisualizationGrid from "./components/VisualizationGrid";
import InsightCard       from "./components/InsightCard";
import LoadingSpinner    from "./components/LoadingSpinner";
import { generateDashboard } from "./services/api";


export default function App() {
  const [file,    setFile]    = useState(null);
  const [prompt,  setPrompt]  = useState("");
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);

  const handleGenerate = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const result = await generateDashboard(file, prompt);
      setData(result);
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setFile(null);
    setPrompt("");
    setData(null);
    setError(null);
  };

  return (
    <div className="app">
      {/* ── Header ── */}
      <header className="header">
        <div className="header-inner">
          <div className="logo">
            <span className="brand-icon">◈</span>
            <span className="logo-text">TalkingBI</span>
          </div>
          <p className="header-tag">AI-powered Business Intelligence Dashboard</p>
        </div>
      </header>

      {/* ── Upload + Prompt Panel ── */}
      <main className="app-main">
        {!data && !loading && (
          <section className="upload-section">
            <div className="upload-card">
              <h2 className="upload-title">Upload your dataset</h2>
              <p className="upload-subtitle">
                CSV or Excel — any schema, any industry. TalkingBI adapts automatically.
              </p>
              <FileUpload file={file} onFileChange={setFile} />
              <PromptBar
                prompt={prompt}
                onPromptChange={setPrompt}
                onGenerate={handleGenerate}
                disabled={!file || loading}
              />
              {error && (
                <div className="error-banner" role="alert">
                  <span className="error-icon">⚠</span>
                  <span>{error}</span>
                </div>
              )}
            </div>
          </section>
        )}

        {/* ── Loading ── */}
        {loading && <LoadingSpinner />}

        {/* ── Dashboard Output ── */}
        {data && !loading && (
          <div className="dashboard-output">
            {/* top action bar */}
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
              <button className="btn-reset" onClick={handleReset}>
                ← New Dataset
              </button>
            </div>

            {/* executive summary */}
            {data.executive_summary?.length > 0 && (
              <ExecutiveSummary bullets={data.executive_summary} />
            )}

            {/* dataset profile */}
            {data.dataset_profile && (
              <DatasetProfile profile={data.dataset_profile} />
            )}

            {/* visualizations */}
            {data.visualizations?.length > 0 ? (
              <VisualizationGrid visualizations={data.visualizations} />
            ) : (
              <div className="empty-state">
                <span className="empty-icon">📊</span>
                <p>No visualizations could be generated for this dataset.</p>
              </div>
            )}

            {/* insights */}
            {data.insights?.length > 0 && (
              <section className="insights-section">
                <h3 className="section-heading">
                  <span className="section-icon">🔍</span> Data Insights
                </h3>
                <div className="insights-grid">
                  {data.insights.map((insight, i) => (
                    <InsightCard key={i} insight={insight} />
                  ))}
                </div>
              </section>
            )}

            {error && (
              <div className="error-banner" role="alert">
                <span className="error-icon">⚠</span>
                <span>{error}</span>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}