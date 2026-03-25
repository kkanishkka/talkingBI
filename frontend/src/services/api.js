// src/services/api.js
// ─────────────────────────────────────────────────────────────────────
// Integrates with TalkingBI's /dashboard endpoint.
// One multipart POST (file + optional prompt) returns the full
// dynamic dashboard payload. No hardcoded column names anywhere.
// ─────────────────────────────────────────────────────────────────────

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const USE_MOCK  = import.meta.env.VITE_USE_MOCK === "true";

/**
 * Main entry-point used by the frontend.
 * Automatically falls back to mock when VITE_USE_MOCK=true.
 */
export async function generateDashboard(file, prompt = "Give me a complete overview dashboard") {
  return USE_MOCK
    ? mockGenerateDashboard(file, prompt)
    : _realGenerateDashboard(file, prompt);
}

async function _realGenerateDashboard(file, prompt) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("prompt", prompt);

  const response = await fetch(`${BASE_URL}/dashboard`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    let message = `Server error: ${response.status}`;
    try {
      const errBody = await response.json();
      message = errBody.detail || errBody.message || message;
    } catch (_) { /* ignore */ }
    throw new Error(message);
  }

  return response.json();
}

// ─────────────────────────────────────────────────────────────────────
// MOCK — exact same contract as /dashboard
// ─────────────────────────────────────────────────────────────────────
async function mockGenerateDashboard(_file, _prompt) {
  await new Promise((r) => setTimeout(r, 1600));

  return {
    executive_summary:
      "This dashboard analyses 3,241 records across 6 columns. It is designed to support " +
      "comparison and distribution analysis through 4 recommended visualizations. The dataset " +
      "contains a mix of categorical and numeric fields with no significant null-value issues.",

    dataset_profile: {
      rows: 3241,
      columns: 6,
      column_names: ["Region", "Category", "Sales", "Profit", "OrderDate", "Segment"],
      column_details: [
        { name: "Region",    dtype: "object",          role: "dimension", unique_count: 4,    null_percentage: 0   },
        { name: "Category",  dtype: "object",          role: "dimension", unique_count: 3,    null_percentage: 0   },
        { name: "Sales",     dtype: "float64",         role: "metric",    unique_count: 1861, null_percentage: 0   },
        { name: "Profit",    dtype: "float64",         role: "metric",    unique_count: 1492, null_percentage: 0.2 },
        { name: "OrderDate", dtype: "datetime64[ns]",  role: "date",      unique_count: 1237, null_percentage: 0   },
        { name: "Segment",   dtype: "object",          role: "dimension", unique_count: 3,    null_percentage: 0   },
      ],
    },

    insights: [
      {
        title: "Sales Concentration in Technology",
        insight_text: "The Technology category accounts for the largest share of total sales across all regions.",
        category: "comparison",
        priority: "high",
        evidence_fields: ["Category", "Sales"],
        confidence: 0.88,
      },
      {
        title: "Western Region Outperforms Peers",
        insight_text: "The West region consistently shows above-average sales and profit margins.",
        category: "distribution",
        priority: "high",
        evidence_fields: ["Region", "Profit"],
        confidence: 0.85,
      },
      {
        title: "Corporate Segment Drives Revenue",
        insight_text: "The Corporate segment generates the highest aggregate revenue despite fewer orders.",
        category: "comparison",
        priority: "medium",
        evidence_fields: ["Segment", "Sales"],
        confidence: 0.78,
      },
    ],

    visualizations: [
      {
        chart_type: "bar",
        title: "Sales by Category",
        x_field: "Category",
        y_field: "value",
        why_this_chart: "A bar chart is effective for comparing category values clearly.",
        confidence: 0.88,
        data: [
          { Category: "Technology",      value: 836154 },
          { Category: "Furniture",       value: 741999 },
          { Category: "Office Supplies", value: 719047 },
        ],
      },
      {
        chart_type: "bar",
        title: "Profit by Region",
        x_field: "Region",
        y_field: "value",
        why_this_chart: "A bar chart compares regional performance side by side.",
        confidence: 0.84,
        data: [
          { Region: "West",    value: 108418 },
          { Region: "East",    value: 91523  },
          { Region: "Central", value: 39706  },
          { Region: "South",   value: 46749  },
        ],
      },
      {
        chart_type: "pie",
        title: "Orders by Segment",
        label_field: "Segment",
        value_field: "value",
        why_this_chart: "A pie chart shows proportional split across a small category set.",
        confidence: 0.8,
        data: [
          { Segment: "Consumer",    value: 1150 },
          { Segment: "Corporate",   value: 1282 },
          { Segment: "Home Office", value: 809  },
        ],
      },
      {
        chart_type: "line",
        title: "Sales trend over time",
        x_field: "OrderDate",
        y_field: "value",
        why_this_chart: "A line chart reveals momentum and seasonal patterns.",
        confidence: 0.9,
        data: [
          { OrderDate: "2021-01", value: 42000 },
          { OrderDate: "2021-04", value: 58000 },
          { OrderDate: "2021-07", value: 71000 },
          { OrderDate: "2021-10", value: 95000 },
          { OrderDate: "2022-01", value: 61000 },
          { OrderDate: "2022-04", value: 83000 },
        ],
      },
    ],
  };
}