// src/components/DatasetProfile.jsx
// Displays a concise dataset profile: row/column counts + typed column table.

import { useState } from "react";

const ROLE_LABELS = {
  metric:    { label: "Metric",    className: "role-metric" },
  dimension: { label: "Category",  className: "role-dimension" },
  date:      { label: "Date/Time", className: "role-date" },
};

export default function DatasetProfile({ profile }) {
  const [expanded, setExpanded] = useState(false);

  if (!profile) return null;

  const {
    rows = 0,
    columns = 0,
    column_details = [],
  } = profile;

  const metrics    = column_details.filter(c => c.role === "metric").length;
  const categories = column_details.filter(c => c.role === "dimension").length;
  const dates      = column_details.filter(c => c.role === "date").length;

  // show first 6 by default, expand on click
  const visible = expanded ? column_details : column_details.slice(0, 6);

  return (
    <section className="dataset-profile">
      {/* section heading */}
      <h3 className="section-heading">
        <span className="section-icon">🗂</span> Dataset Profile
      </h3>

      {/* stat pills */}
      <div className="profile-stats-row">
        <div className="profile-stat">
          <span className="stat-value">{rows.toLocaleString()}</span>
          <span className="stat-label">Rows</span>
        </div>
        <div className="profile-stat">
          <span className="stat-value">{columns}</span>
          <span className="stat-label">Columns</span>
        </div>
        <div className="profile-stat">
          <span className="stat-value">{metrics}</span>
          <span className="stat-label">Metrics</span>
        </div>
        <div className="profile-stat">
          <span className="stat-value">{categories}</span>
          <span className="stat-label">Categories</span>
        </div>
        {dates > 0 && (
          <div className="profile-stat">
            <span className="stat-value">{dates}</span>
            <span className="stat-label">Date Fields</span>
          </div>
        )}
      </div>

      {/* column table */}
      {column_details.length > 0 && (
        <>
          <p className="profile-columns-heading">Column Details</p>
          <table className="profile-columns-table">
            <thead>
              <tr>
                <th>Column</th>
                <th>Type</th>
                <th>Role</th>
                <th>Unique</th>
                <th>Null %</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((col) => {
                const roleInfo = ROLE_LABELS[col.role] || { label: col.role, className: "" };
                const isNullWarning = col.null_percentage > 10;
                return (
                  <tr key={col.name}>
                    <td className="col-name">{col.name}</td>
                    <td>{col.dtype}</td>
                    <td>
                      <span className={`role-badge ${roleInfo.className}`}>
                        {roleInfo.label}
                      </span>
                    </td>
                    <td>{col.unique_count?.toLocaleString() ?? "—"}</td>
                    <td className={isNullWarning ? "null-warn" : ""}>
                      {col.null_percentage != null
                        ? `${col.null_percentage}%`
                        : "—"}
                      {isNullWarning && " ⚠"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {column_details.length > 6 && (
            <button
              className="btn-reset"
              style={{ marginTop: 12, fontSize: 12 }}
              onClick={() => setExpanded((e) => !e)}
            >
              {expanded
                ? "Show less"
                : `Show all ${column_details.length} columns`}
            </button>
          )}
        </>
      )}
    </section>
  );
}