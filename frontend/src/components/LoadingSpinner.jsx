// src/components/LoadingSpinner.jsx
// Shows an animated spinner with step-by-step progress indicators
// that mirror what the backend is actually doing.

import { useEffect, useState } from "react";

const STEPS = [
  "Parsing dataset schema…",
  "Detecting column types and roles…",
  "Recommending chart types…",
  "Generating data-driven insights…",
  "Materialising chart data…",
  "Finalising dashboard…",
];

export default function LoadingSpinner() {
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setActiveStep((s) => Math.min(s + 1, STEPS.length - 1));
    }, 900);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="loading-overlay">
      <div className="spinner-ring" />
      <p className="loading-text">Analysing your dataset…</p>
      <div className="loading-steps">
        {STEPS.map((step, i) => (
          <div
            key={i}
            className={`loading-step ${i === activeStep ? "active" : ""}`}
          >
            <span className="step-dot" />
            {step}
          </div>
        ))}
      </div>
    </div>
  );
}