// src/components/PromptBar.jsx
// Natural-language prompt input shown alongside the file uploader.

export default function PromptBar({ value, onChange, disabled }) {
  return (
    <div style={{ position: "relative", flex: 2, minWidth: 260 }}>
      <span style={{
        position: "absolute",
        left: 14,
        top: "50%",
        transform: "translateY(-50%)",
        fontSize: 16,
        color: "var(--text-muted)",
        pointerEvents: "none",
      }}>
        ◎
      </span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder='e.g. "Show me a sales trend and category breakdown"'
        style={{
          width: "100%",
          background: "var(--bg-2)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-lg)",
          padding: "14px 16px 14px 40px",
          color: "var(--text-primary)",
          fontFamily: "var(--font-body)",
          fontSize: 14,
          outline: "none",
          transition: "border-color 0.2s",
        }}
        onFocus={(e) => (e.target.style.borderColor = "var(--accent)")}
        onBlur={(e)  => (e.target.style.borderColor = "var(--border)")}
      />
    </div>
  );
}