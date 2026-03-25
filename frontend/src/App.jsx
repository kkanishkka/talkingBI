// src/App.jsx — TalkingBI dynamic dashboard
import { useState } from "react";
import FileUpload       from "./components/FileUpload";
import PromptBar        from "./components/PromptBar";
import InsightCard      from "./components/InsightCard";
import ExecutiveSummary from "./components/ExecutiveSummary";
import DatasetProfile   from "./components/DatasetProfile";
import VisualizationGrid from "./components/VisualizationGrid";
import LoadingSpinner   from "./components/LoadingSpinner";
import { generateDashboard } from "./services/api";
import "./App.css";

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
      const result = await generateDashboard(file, prompt || undefined);
      setData(result);
    } catch (err) {
      setError(err.message || "Failed to generate dashboard. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const priorityOrder = { high: 0, medium: 1, low: 2 };
  const sortedInsights = data?.insights
    ? [...data.insights].sort(
        (a, b) =>
          (priorityOrder[a.priority?.toLowerCase()] ?? 9) -
          (priorityOrder[b.priority?.toLowerCase()] ?? 9)
      )
    : [];

  return (
    <div className="app">
      {/* ── Header ── */}
      <header className="header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-mark">◈</span>
            <span className="logo-text">TalkingBI</span>
          </div>
          <span className="header-tag">AI-Powered BI Dashboard</span>
        </div>
      </header>

      <main className="main">

        {/* ── 01 Upload + Prompt ── */}
        <section className="upload-section">
          <div className="section-label">01 — DATA SOURCE</div>
          <h2 className="section-title">Upload your dataset</h2>
          <p className="section-sub">
            CSV or Excel. Add an optional natural-language goal to guide the analysis.
          </p>

          <div className="upload-row" style={{ flexWrap: "wrap", gap: 12 }}>
            <FileUpload file={file} onFileSelect={setFile} />
            <PromptBar value={prompt} onChange={setPrompt} disabled={loading} />
            <button
              className="btn-generate"
              onClick={handleGenerate}
              disabled={!file || loading}
            >
              {loading ? "Analysing…" : "Generate Dashboard →"}
            </button>
          </div>

          {error && (
            <div className="error-banner">
              <span className="error-icon">⚠</span> {error}
            </div>
          )}
        </section>

        {/* ── Loading ── */}
        {loading && <LoadingSpinner />}

        {/* ── Results ── */}
        {data && !loading && (
          <>
            {/* 02 — Dataset Profile */}
            {data.dataset_profile && (
              <section className="result-section">
                <div className="section-label">02 — DATASET PROFILE</div>
                <DatasetProfile profile={data.dataset_profile} />
              </section>
            )}

            {/* 03 — Executive Summary */}
            <section className="result-section">
              <div className="section-label">03 — EXECUTIVE SUMMARY</div>
              <ExecutiveSummary summary={data.executive_summary} />
            </section>

            {/* 04 — Visualizations */}
            {data.visualizations?.length > 0 && (
              <section className="result-section">
                <div className="section-label">
                  04 — VISUALIZATIONS
                  <span className="insight-count">{data.visualizations.length} charts</span>
                </div>
                <VisualizationGrid visualizations={data.visualizations} />
              </section>
            )}

            {/* 05 — Insights */}
            {sortedInsights.length > 0 && (
              <section className="result-section">
                <div className="section-label">
                  05 — INSIGHTS
                  <span className="insight-count">{sortedInsights.length} findings</span>
                </div>
                <div className="insights-grid">
                  {sortedInsights.map((ins, i) => (
                    <InsightCard key={i} insight={ins} index={i} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </main>

      <footer className="footer">
        TalkingBI · Powered by AI · {new Date().getFullYear()}
      </footer>
    </div>
  );
}