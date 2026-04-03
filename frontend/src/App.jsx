import { useState } from "react";
import "./App.css";

import {
  askQuestion,
  connectDatabase,
  selectTable,
} from "./services/api";

import ExecutiveSummary from "./components/ExecutiveSummary";
import AnalysisReport from "./components/AnalysisReport";
import VisualizationGrid from "./components/VisualizationGrid";
import AssumptionBlock from "./components/AssumptionBlock";
import DatasetProfile from "./components/DatasetProfile";
import LoadingSpinner from "./components/LoadingSpinner";

function normalizeTables(result) {
  // support multiple backend response shapes
  const rawTables =
    result?.tables ||
    result?.available_tables ||
    result?.table_options ||
    result?.data?.tables ||
    [];

  if (!Array.isArray(rawTables)) return [];

  return rawTables.map((t, index) => {
    // case 1: backend sends string table names
    if (typeof t === "string") {
      return {
        name: t,
        type: "table",
        row_count: null,
        col_count: null,
        priority: "unknown",
        key: `${t}-${index}`,
      };
    }

    // case 2: backend sends object table metadata
    return {
      name: t.name || t.table_name || `table_${index}`,
      type: t.type || t.table_type || "table",
      row_count:
        typeof t.row_count === "number"
          ? t.row_count
          : typeof t.rows === "number"
          ? t.rows
          : null,
      col_count:
        typeof t.col_count === "number"
          ? t.col_count
          : typeof t.columns === "number"
          ? t.columns
          : null,
      priority: t.priority || "unknown",
      key: t.name || t.table_name || `table_${index}`,
    };
  });
}

function formatTableLabel(t) {
  const parts = [t.name];

  if (t.type) parts.push(t.type);
  if (typeof t.row_count === "number")
    parts.push(`${t.row_count.toLocaleString()} rows`);
  if (typeof t.col_count === "number") parts.push(`${t.col_count} cols`);
  if (t.priority === "analytical") parts.push("⭐");

  return parts.join(" · ");
}

export default function App() {
  const [connectionString, setConnectionString] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [tables, setTables] = useState([]);
  const [selectedTable, setSelectedTable] = useState("");
  const [prompt, setPrompt] = useState("");
  const [data, setData] = useState(null);
  const [connected, setConnected] = useState(false);
  const [tableReady, setTableReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeLayout, setActiveLayout] = useState(0);

  async function handleConnect() {
    setLoading(true);
    setError("");
    setData(null);

    try {
      const result = await connectDatabase(connectionString);
      console.log("CONNECT RESPONSE:", result);

      const normalizedTables = normalizeTables(result);

      setSessionId(result.session_id || result.sessionId || "");
      setTables(normalizedTables);
      setConnected(true);
      setTableReady(false);

      if (normalizedTables.length === 0) {
        setError(
          "Connected successfully, but no tables were returned by the backend."
        );
      }
    } catch (err) {
      setError(err.message || "Connection failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectTable() {
    if (!selectedTable) return;

    setLoading(true);
    setError("");

    try {
      await selectTable(sessionId, selectedTable);
      setTableReady(true);
    } catch (err) {
      setError(err.message || "Table selection failed");
    } finally {
      setLoading(false);
    }
  }

  async function runPrompt(query) {
    if (!query.trim()) return;

    setLoading(true);
    setError("");

    try {
      const result = await askQuestion(sessionId, query);
      console.log("ASK RESPONSE:", result);
      setData(result);
      setActiveLayout(0);
    } catch (err) {
      setError(err.message || "Query failed");
    } finally {
      setLoading(false);
    }
  }

  const handleAsk = () => runPrompt(prompt);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1 className="app-title">TalkingBI</h1>
          <p className="header-tagline">Supabase-connected AI BI assistant</p>
          {sessionId && (
            <span className="session-badge" title={`Session: ${sessionId}`}>
              ● Session active
            </span>
          )}
        </div>
      </header>

      <main className="app-main">
        {!connected && (
          <section className="upload-section">
            <div className="upload-card">
              <h2 className="upload-title">Connect your database</h2>
              <p className="upload-subtitle">
                Paste your read-only Supabase PostgreSQL connection string.
              </p>

              <textarea
                rows={4}
                value={connectionString}
                onChange={(e) => setConnectionString(e.target.value)}
                placeholder="postgresql+psycopg2://talkingbi_readonly:password@host:port/postgres?sslmode=require"
                style={{ width: "100%", padding: 12, borderRadius: 12 }}
              />

              <button
                className="generate-button"
                onClick={handleConnect}
                disabled={loading || !connectionString.trim()}
                style={{ marginTop: 12 }}
              >
                {loading ? "Connecting..." : "Connect"}
              </button>
            </div>
          </section>
        )}

        {connected && !tableReady && (
          <section className="upload-section">
            <div className="upload-card">
              <h2 className="upload-title">Select table</h2>

              <select
                value={selectedTable}
                onChange={(e) => setSelectedTable(e.target.value)}
                style={{ width: "100%", padding: 12, borderRadius: 12 }}
              >
                <option value="">Choose a table</option>
                {tables.map((t) => (
                  <option key={t.key} value={t.name}>
                    {formatTableLabel(t)}
                  </option>
                ))}
              </select>

              <button
                className="generate-button"
                onClick={handleSelectTable}
                disabled={loading || !selectedTable}
                style={{ marginTop: 12 }}
              >
                {loading ? "Loading..." : "Use this table"}
              </button>
            </div>
          </section>
        )}

        {tableReady && (
          <section className="upload-section">
            <div className="upload-card">
              <h2 className="upload-title">Ask your data a question</h2>
              <p className="upload-subtitle">
                Connected table: <strong>{selectedTable}</strong>
              </p>

              <textarea
                rows={3}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="e.g. show top 5 categories by sales"
                style={{ width: "100%", padding: 12, borderRadius: 12 }}
              />

              <button
                className="generate-button"
                onClick={handleAsk}
                disabled={loading || !prompt.trim()}
                style={{ marginTop: 12 }}
              >
                {loading ? "Analyzing..." : "Generate dashboard"}
              </button>
            </div>
          </section>
        )}

        {error && (
          <div style={{ color: "red", marginTop: 16 }}>
            {error}
          </div>
        )}

        {data && (
          <section style={{ marginTop: 24 }}>
            <h2>Dashboard</h2>
            {data.needs_clarification ? (
              <div className="clarification">
                <h3>Needs clarification</h3>
                <p>{data.message}</p>
                <pre>{JSON.stringify(data.clarification, null, 2)}</pre>
              </div>
            ) : (
              <div className="dashboard">
                {data.executive_summary &&
                  data.executive_summary.length > 0 && (
                    <ExecutiveSummary bullets={data.executive_summary} />
                  )}

                {data.analysis_report && (
                  <AnalysisReport report={data.analysis_report} />
                )}

                {data.visualizations &&
                  data.visualizations.length > 0 &&
                  data.layouts &&
                  data.layouts.length > 0 && (
                    <VisualizationGrid
                      visualizations={data.visualizations}
                      layout={data.layouts[0]}
                    />
                  )}

                {data.assumptions &&
                  Object.values(data.assumptions).some((v) => v) && (
                    <AssumptionBlock assumptions={data.assumptions} />
                  )}

                {data.dataset_profile && (
                  <DatasetProfile profile={data.dataset_profile} />
                )}

                {data.warnings && data.warnings.length > 0 && (
                  <div className="warnings">
                    <h4>Warnings</h4>
                    <ul>
                      {data.warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {!data.executive_summary &&
                  !data.analysis_report &&
                  !data.visualizations && (
                    <pre>{JSON.stringify(data, null, 2)}</pre>
                  )}
              </div>
            )}
          </section>
        )}

        {loading && (
          <div style={{ marginTop: 24, textAlign: "center" }}>
            <LoadingSpinner />
            <p>Generating dashboard...</p>
          </div>
        )}
      </main>
    </div>
  );
}