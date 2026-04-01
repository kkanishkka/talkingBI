// src/components/DatasetProfile.jsx
import { useState } from "react";

const ROLE_LABELS = {
  metric:    { label:"Metric",    cls:"role-metric" },
  dimension: { label:"Category",  cls:"role-dimension" },
  date:      { label:"Date/Time", cls:"role-date" },
};
const HINT_LABELS = {
  likely_target:"target", currency:"currency", count_field:"count",
  score:"score", category_key:"category", likely_id:"id",
  high_cardinality:"high-card", percentage:"percent",
};

export default function DatasetProfile({ profile }) {
  const [expanded, setExpanded] = useState(false);
  if (!profile) return null;

  const { rows=0, columns=0, column_details=[] } = profile;
  const metrics   = column_details.filter(c=>c.role==="metric").length;
  const cats      = column_details.filter(c=>c.role==="dimension").length;
  const dates     = column_details.filter(c=>c.role==="date").length;
  const targets   = column_details.filter(c=>c.semantic_hint==="likely_target").length;

  const visible = expanded ? column_details : column_details.slice(0,6);

  return (
    <section className="dataset-profile">
      <h3 className="section-heading">
        <span className="section-icon">🗂</span> Dataset Profile
      </h3>

      <div className="profile-stats-row">
        {[
          { v: rows.toLocaleString(),   l: "Rows" },
          { v: columns,                 l: "Columns" },
          { v: metrics,                 l: "Metrics" },
          { v: cats,                    l: "Categories" },
          dates   > 0 && { v: dates,   l: "Date Fields" },
          targets > 0 && { v: targets, l: "Target Cols" },
        ].filter(Boolean).map((s,i) => (
          <div key={i} className="profile-stat">
            <span className="stat-value">{s.v}</span>
            <span className="stat-label">{s.l}</span>
          </div>
        ))}
      </div>

      {column_details.length > 0 && (
        <>
          <p className="profile-columns-heading">Column Details</p>
          <table className="profile-columns-table">
            <thead>
              <tr><th>Column</th><th>Type</th><th>Role</th><th>Hint</th><th>Unique</th><th>Null %</th></tr>
            </thead>
            <tbody>
              {visible.map(col => {
                const ri = ROLE_LABELS[col.role] || { label:col.role, cls:"" };
                const hl = HINT_LABELS[col.semantic_hint];
                return (
                  <tr key={col.name}>
                    <td className="col-name">{col.name}</td>
                    <td>{col.dtype}</td>
                    <td><span className={`role-badge ${ri.cls}`}>{ri.label}</span></td>
                    <td>
                      {hl && (
                        <span className={`hint-badge${col.semantic_hint==="likely_target"?" hint-target":""}`}>
                          {hl}
                        </span>
                      )}
                    </td>
                    <td>{col.unique_count?.toLocaleString() ?? "—"}</td>
                    <td className={col.null_percentage > 10 ? "null-warn" : ""}>
                      {col.null_percentage != null ? `${col.null_percentage}%` : "—"}
                      {col.null_percentage > 10 && " ⚠"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {column_details.length > 6 && (
            <button className="btn-reset" style={{marginTop:10,fontSize:11}}
                    onClick={() => setExpanded(e=>!e)}>
              {expanded ? "Show less" : `Show all ${column_details.length} columns`}
            </button>
          )}
        </>
      )}
    </section>
  );
}