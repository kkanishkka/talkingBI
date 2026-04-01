// src/components/LoadingSpinner.jsx
import { useEffect, useState } from "react";

const STEPS = [
  "Parsing dataset schema…",
  "Detecting column roles and semantic types…",
  "Understanding your question…",
  "Building analysis plan…",
  "Executing computation…",
  "Validating results…",
  "Selecting chart type…",
  "Generating insights…",
];

export default function LoadingSpinner() {
  const [activeStep, setActiveStep] = useState(0);
  useEffect(() => {
    const iv = setInterval(
      () => setActiveStep(s => Math.min(s + 1, STEPS.length - 1)),
      800
    );
    return () => clearInterval(iv);
  }, []);

  return (
    <div className="loading-overlay">
      <div className="spinner-ring" />
      <p className="loading-text">Analysing your dataset…</p>
      <div className="loading-steps">
        {STEPS.map((step, i) => (
          <div key={i} className={`loading-step${i === activeStep ? " active" : ""}`}>
            <span className="step-dot" />
            {step}
          </div>
        ))}
      </div>
    </div>
  );
}