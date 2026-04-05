// App.jsx — TalkingBI v6 (auto table selection + explanation in chat)
import { useState, useCallback } from "react";
import "./App.css";

import { connectDatabase, selectTable, chatQuery } from "./services/api";
import ChatPanel from "./components/Chatpanel";
import ChatInput from "./components/Chatinput";
import DashboardWorkspace from "./components/DashboardWorkspace";
import VoiceMicButton from "./components/VoiceMicButton";
import LoadingSpinner from "./components/LoadingSpinner";

function normalizeTables(result) {
  const raw = result?.tables || result?.available_tables || result?.data?.tables || [];
  if (!Array.isArray(raw)) return [];
  return raw.map((t, i) => {
    if (typeof t === "string")
      return { name: t, type: "table", row_count: null, col_count: null, priority: "unknown", key: `${t}-${i}` };
    return {
      name:      t.name || t.table_name || `table_${i}`,
      type:      t.type || "table",
      row_count: t.row_count ?? t.rows ?? null,
      col_count: t.col_count ?? t.columns ?? null,
      priority:  t.priority || "unknown",
      key:       t.name || `table_${i}`,
    };
  });
}

function formatTableLabel(t) {
  const p = [t.name];
  if (t.type)      p.push(t.type);
  if (t.row_count != null) p.push(`${Number(t.row_count).toLocaleString()} rows`);
  if (t.col_count != null) p.push(`${t.col_count} cols`);
  if (t.priority === "analytical") p.push("⭐");
  return p.join(" · ");
}

let _id = 0;
const mkMsg = (role, text, extras = {}) => ({
  id: ++_id, role, text, timestamp: Date.now(), ...extras,
});

export default function App() {
  const [connStr,       setConnStr]       = useState("");
  const [sessionId,     setSessionId]     = useState("");
  const [tables,        setTables]        = useState([]);
  const [selectedTable, setSelectedTable] = useState("");
  const [connected,     setConnected]     = useState(false);
  const [tableReady,    setTableReady]    = useState(false);
  const [messages,      setMessages]      = useState([]);
  const [dashboard,     setDashboard]     = useState(null);
  const [loading,       setLoading]       = useState(false);
  const [error,         setError]         = useState("");
  // For manual table override UI
  const [showTablePicker, setShowTablePicker] = useState(false);

  // ── Connect ────────────────────────────────────────────────────
  async function handleConnect() {
    setLoading(true); setError("");
    try {
      const r = await connectDatabase(connStr);

      setSessionId(r.session_id || "");
      setTables(normalizeTables(r));
      setConnected(true);

      // ── Auto-selected path (v6) ──────────────────────────────
      if (r.table_ready && r.auto_selected_table) {
        setSelectedTable(r.auto_selected_table);
        setTableReady(true);
        setMessages([
          mkMsg("assistant",
            `Connected to **${r.auto_selected_table}**. ` +
            (r.selection_reason ? `*(${r.selection_reason})* ` : "") +
            `What would you like to know?`
          ),
        ]);
      } else {
        // Fallback: show table picker (old flow)
        setTableReady(false);
        if (!normalizeTables(r).length) setError("Connected but no tables found.");
      }
    } catch (e) {
      setError(e.message || "Connection failed");
    } finally {
      setLoading(false);
    }
  }

  // ── Manual table select (override) ────────────────────────────
  async function handleSelectTable(tableName) {
    if (!tableName) return;
    setLoading(true); setError("");
    try {
      await selectTable(sessionId, tableName);
      setSelectedTable(tableName);
      setTableReady(true);
      setShowTablePicker(false);
      setMessages([
        mkMsg("assistant", `Switched to **${tableName}**. What would you like to know?`),
      ]);
    } catch (e) {
      setError(e.message || "Table selection failed");
    } finally {
      setLoading(false);
    }
  }

  // ── Chat send ──────────────────────────────────────────────────
  const handleSend = useCallback(async (text) => {
    if (!text.trim() || loading) return;
    setMessages(p => [...p, mkMsg("user", text)]);
    setLoading(true); setError("");
    try {
      const res = await chatQuery(sessionId, text);

      // Build assistant message with explanation
      let answerText = res.assistant_message || "";
      if (!answerText && res.needs_clarification) answerText = res.message;
      if (!answerText) answerText = "Dashboard updated.";

      // Append the explanation if present and not already in the message
      const explanation = res.executed_query?.explanation
        || (res.analysis_report?.query_intent?.assumptions?.[0] || "");
      if (explanation && !answerText.includes(explanation)) {
        answerText = answerText + `\n\n*${explanation}*`;
      }

      setMessages(p => [...p, mkMsg("assistant", answerText, {
        resolvedPrompt: res.resolved_prompt,
        wasFollowup:    res.was_followup,
        executedQuery:  res.executed_query,
      })]);
      setDashboard(res);
    } catch (e) {
      const t = e.message || "Something went wrong.";
      setError(t);
      setMessages(p => [...p, mkMsg("assistant", `❌ ${t}`)]);
    } finally {
      setLoading(false);
    }
  }, [sessionId, loading]);

  // ── Voice ──────────────────────────────────────────────────────
  const handleVoiceResult = useCallback((data) => {
    setMessages(p => [
      ...p,
      mkMsg("user", `🎤 ${data.transcribed_text || ""}`),
      mkMsg("assistant", data.assistant_message || "Voice analysis complete.", {
        executedQuery: data.executed_query,
      }),
    ]);
    setDashboard(data);
    setError("");
  }, []);

  const handleVoiceError = useCallback((e) => {
    setError(e);
    setMessages(p => [...p, mkMsg("assistant", `❌ ${e}`)]);
  }, []);

  // ── Connect screen ─────────────────────────────────────────────
  if (!connected) {
    return (
      <div className="app-shell">
        <AppHeader />
        <main className="setup-main">
          <div className="setup-card">
            <h2>Connect your database</h2>
            <p className="setup-subtitle">
              Paste a read-only Supabase PostgreSQL connection string.
              The best table will be selected automatically.
            </p>
            <textarea
              rows={4}
              value={connStr}
              onChange={e => setConnStr(e.target.value)}
              placeholder="postgresql+psycopg2://user:pass@host:5432/db?sslmode=require"
            />
            {error && <p className="setup-error">{error}</p>}
            <button
              className="primary-btn"
              onClick={handleConnect}
              disabled={loading || !connStr.trim()}
            >
              {loading ? <><LoadingSpinner size="sm" /> Connecting…</> : "Connect"}
            </button>
          </div>
        </main>
      </div>
    );
  }

  // ── Manual table picker (fallback or override) ─────────────────
  if (!tableReady) {
    return (
      <div className="app-shell">
        <AppHeader sessionId={sessionId} />
        <main className="setup-main">
          <div className="setup-card">
            <h2>Select a table</h2>
            <select
              defaultValue=""
              onChange={e => e.target.value && handleSelectTable(e.target.value)}
            >
              <option value="">Choose a table…</option>
              {tables.map(t => (
                <option key={t.key} value={t.name}>{formatTableLabel(t)}</option>
              ))}
            </select>
            {error && <p className="setup-error">{error}</p>}
            {loading && <LoadingSpinner size="sm" />}
          </div>
        </main>
      </div>
    );
  }

  // ── Main workspace ─────────────────────────────────────────────
  return (
    <div className="app-shell">
      <AppHeader sessionId={sessionId} tableName={selectedTable} />
      <div className="workspace-layout">
        <aside className="chat-sidebar">
          <ChatPanel messages={messages} loading={loading} />
          <div className="chat-input-wrapper">
            <div className="chat-input-with-voice">
              <VoiceMicButton
                sessionId={sessionId}
                onResult={handleVoiceResult}
                onError={handleVoiceError}
                disabled={loading}
              />
              <ChatInput
                onSend={handleSend}
                disabled={loading}
                placeholder={`Ask about ${selectedTable}…`}
              />
            </div>
            {error && <p className="chat-error">{error}</p>}
          </div>

          {/* Table override button */}
          {tables.length > 1 && (
            <div className="table-override-bar">
              {showTablePicker ? (
                <select
                  defaultValue=""
                  onChange={e => e.target.value && handleSelectTable(e.target.value)}
                >
                  <option value="">Switch table…</option>
                  {tables.map(t => (
                    <option key={t.key} value={t.name}>{formatTableLabel(t)}</option>
                  ))}
                </select>
              ) : (
                <button
                  className="secondary-btn"
                  onClick={() => setShowTablePicker(true)}
                >
                  Switch table
                </button>
              )}
            </div>
          )}
        </aside>

        <main className="dashboard-pane">
          {loading && !dashboard && (
            <div className="workspace-loading">
              <LoadingSpinner />
              <p>Generating dashboard…</p>
            </div>
          )}
          <DashboardWorkspace
            dashboard={dashboard}
            onSuggestionClick={handleSend}
            loading={loading}
          />
        </main>
      </div>
    </div>
  );
}

function AppHeader({ sessionId, tableName }) {
  return (
    <header className="app-header">
      <div className="header-left">
        <h1 className="app-title">TalkingBI</h1>
        <p className="header-tagline">Voice · Chat · Dashboard</p>
      </div>
      <div className="header-right">
        {tableName && (
          <span className="header-badge table-badge">📋 {tableName}</span>
        )}
        {sessionId && (
          <span
            className="header-badge session-badge"
            title={`Session: ${sessionId}`}
          >
            ● Session active
          </span>
        )}
      </div>
    </header>
  );
}