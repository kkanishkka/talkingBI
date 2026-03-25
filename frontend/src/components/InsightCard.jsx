// src/components/InsightCard.jsx
export default function InsightCard({ insight, index }) {
  const { title, insight_text, category, priority = "medium" } = insight;

  const priorityClass = {
    high:   "priority-high",
    medium: "priority-medium",
    low:    "priority-low",
  }[priority.toLowerCase()] || "priority-medium";

  return (
    <div
      className="insight-card"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <div className="insight-card-top">
        <div className="insight-card-title">{title}</div>
        <span className={`priority-badge ${priorityClass}`}>{priority}</span>
      </div>

      <p className="insight-card-text">{insight_text}</p>

      {category && (
        <div className="insight-card-category">⌂ {category}</div>
      )}
    </div>
  );
}