// src/components/DatasetProfile.jsx
// Shows the profiled schema: row/column counts + column role badges.
// Fully dynamic — nothing hardcoded.

const ROLE_STYLE = {
  metric:    { bg: "rgba(91,141,238,0.12)", color: "var(--blue)",   label: "metric"    },
  dimension: { bg: "rgba(245,166,35,0.10)", color: "var(--accent)", label: "dimension" },
  date:      { bg: "rgba(62,207,142,0.10)", color: "var(--green)",  label: "date"      },
};

function RoleBadge({ role }) {
  const s = ROLE_STYLE[role] || ROLE_STYLE.dimension;
  return (
    <span style={{
      background: s.bg,
      color: s.color,
      fontFamily: "var(--font-mono)",
      fontSize: 9,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
      padding: "2px 7px",
      borderRadius: 4,
    }}>
      {s.label}
    </span>
  );
}

export default function DatasetProfile({ profile }) {
  if (!profile) return null;
  const { rows, columns, column_details } = profile;

  return (
    <div style={{
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-lg)",
      padding: "24px 28px",
    }}>
      {/* summary stats */}
      <div style={{ display: "flex", gap: 32, marginBottom: 20 }}>
        {[
          { label: "Rows",    value: rows.toLocaleString() },
          { label: "Columns", value: columns },
        ].map(({ label, value }) => (
          <div key={label}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 4 }}>
              {label}
            </div>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 26, fontWeight: 700, color: "var(--text-primary)", letterSpacing: "-0.03em" }}>
              {value}
            </div>
          </div>
        ))}
      </div>

      {/* column chips */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {column_details.map((col) => (
          <div key={col.name} style={{
            background: "var(--bg-3)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: "7px 12px",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}>
            <span style={{ fontSize: 13, color: "var(--text-primary)", fontFamily: "var(--font-body)" }}>
              {col.name}
            </span>
            <RoleBadge role={col.role} />
            {col.null_percentage > 0 && (
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--red)" }}>
                {col.null_percentage}% null
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}