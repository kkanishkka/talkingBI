// src/utils/insightEnhancer.js
// ─────────────────────────────────────────────────────────
// Transforms raw insight text into analytical, business-focused
// narratives. Works locally (no API call needed).
// ─────────────────────────────────────────────────────────

const categoryFrames = {
  demographics: {
    prefix: "Demographic analysis indicates",
    suffix: "This cohort warrants targeted intervention strategies and resource reallocation.",
  },
  clinical: {
    prefix: "Clinical data signals",
    suffix: "Proactive care protocols and earlier screening pathways should be evaluated.",
  },
  access: {
    prefix: "Access-equity metrics reveal",
    suffix: "Closing this gap represents both a care-quality imperative and an operational opportunity.",
  },
  utilisation: {
    prefix: "Utilisation patterns suggest",
    suffix: "Reviewing triage workflows could reduce cost-per-episode and improve throughput.",
  },
  default: {
    prefix: "Analysis reveals",
    suffix: "Further investigation is recommended to quantify the downstream impact.",
  },
};

const prioritySignals = {
  high:   "Immediate attention is warranted.",
  medium: "This trend merits monitoring over the coming quarter.",
  low:    "Consider including this in the next strategic review cycle.",
};

/**
 * Enhances a raw insight object into a richer, analytical narrative.
 * @param {{ insight_text: string, category?: string, priority?: string }} insight
 * @returns {string} Enhanced text
 */
export function improveInsightText(insight) {
  const { insight_text, category = "", priority = "medium" } = insight;

  const key = category.toLowerCase();
  const frame = categoryFrames[key] || categoryFrames.default;
  const signal = prioritySignals[priority.toLowerCase()] || prioritySignals.medium;

  // Capitalise first char, strip trailing period
  const core = insight_text.charAt(0).toUpperCase() + insight_text.slice(1).replace(/\.$/, "");

  return `${frame.prefix} that ${core.toLowerCase()}. ${frame.suffix} ${signal}`;
}

/**
 * Example transformations:
 *
 * BEFORE: "Female patients receive fewer specialist referrals despite higher screening attendance."
 * AFTER:  "Access-equity metrics reveal that female patients receive fewer specialist referrals
 *          despite higher screening attendance. Closing this gap represents both a care-quality
 *          imperative and an operational opportunity. Immediate attention is warranted."
 *
 * BEFORE: "Co-occurrence of hypertension and diabetes increased 14% YoY."
 * AFTER:  "Clinical data signals that co-occurrence of hypertension and diabetes increased 14%
 *          YoY. Proactive care protocols and earlier screening pathways should be evaluated.
 *          This trend merits monitoring over the coming quarter."
 */