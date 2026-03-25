// src/components/LoadingSpinner.jsx
export default function LoadingSpinner() {
  return (
    <div className="loading-wrapper">
      <div className="loading-ring" />
      <span className="loading-text">Generating insights…</span>
    </div>
  );
}