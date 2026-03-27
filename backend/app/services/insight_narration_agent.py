"""
app/services/insight_narration_agent.py
════════════════════════════════════════════════════════════════════
Agent 6: Insight Narrator

Replaces: insight_engine.py (for query-driven insights)

Responsibility:
  Given the execution result and query intent, generate business-level
  insights that:
    1. Answer the user's actual question directly
    2. Name specific values (e.g. "Retired: 25.1%")
    3. Provide a "so what?" recommendation
    4. Use comparative language (3x the average, top performer, etc.)
    5. Warn about data caveats if relevant

  Primary: LLM call with structured data in the prompt
  Fallback: Template-based generation from the top rows

Usage:
  from app.services.insight_narration_agent import narrate_insights
  report = narrate_insights(query_intent, execution_result, viz_spec)
════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── LLM helpers ───────────────────────────────────────────────────

def _llm_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))


def _call_llm(system_prompt: str, user_message: str) -> str | None:
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            client = OpenAI()
            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                temperature=0.3,   # slight creativity for narration
                max_tokens=600,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content
        except Exception as exc:
            logger.warning("OpenAI narration call failed: %s", exc)
            return None

    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model=os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307"),
                max_tokens=600,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            return resp.content[0].text
        except Exception as exc:
            logger.warning("Anthropic narration call failed: %s", exc)
            return None

    return None


# ── LLM prompt for narration ──────────────────────────────────────

_NARRATOR_SYSTEM = """You are a senior business analyst writing insights for an executive dashboard.

Given a user's question, the analysis result data, and metric type, produce ONLY a JSON object:

{
  "headline": "one punchy sentence that directly answers the user's question",
  "bullets": [
    "bullet 1 — specific observation with numbers",
    "bullet 2 — comparison or contrast",
    "bullet 3 — implication or pattern",
    "bullet 4 — so-what recommendation"
  ],
  "so_what": "one actionable recommendation sentence",
  "data_caveat": "data quality note or null"
}

Rules:
- Lead with the direct answer to the user's question
- Use **bold** around key values and category names
- For rate metrics: express as percentage (e.g. 25.1%, not 0.251)
- Mention the top performer AND the weakest for comparison
- Compute averages/ratios in your head from the data if needed
- The "so_what" must be actionable (start with a verb: "Target...", "Prioritise...", "Review...")
- bullets array must have exactly 3-4 items
- Output ONLY valid JSON. No markdown. No explanation.
"""


def _format_value(value: Any, metric: str) -> str:
    """Format a numeric value for the prompt context."""
    try:
        f = float(value)
        if metric == "rate":
            return f"{f * 100:.1f}%"
        elif metric in ("count", "sum"):
            return f"{int(f):,}"
        else:
            return f"{f:.2f}"
    except (TypeError, ValueError):
        return str(value)


def _build_narrator_message(
    intent:  dict[str, Any],
    result:  dict[str, Any],
) -> str:
    metric   = intent.get("metric", "count")
    question = intent.get("raw_prompt", "")
    data     = result.get("data", [])
    x_field  = result.get("x_field", "category")
    y_field  = result.get("y_field", "value")
    ml       = result.get("metric_label", "Value")

    # format data for the prompt
    data_lines = []
    for row in data[:15]:  # send top 15 rows to keep prompt short
        x = row.get(x_field, "?")
        y = row.get(y_field)
        data_lines.append(f"  {x}: {_format_value(y, metric)}")

    return (
        f"User question: {question}\n\n"
        f"Metric: {ml} (type: {metric})\n"
        f"Top results:\n" + "\n".join(data_lines) +
        f"\n\nTotal rows in result: {result.get('row_count', len(data))}"
    )


# ── template-based fallback ───────────────────────────────────────

def _template_narrate(
    intent: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """
    Generate structured insights from result data using templates.
    Used when LLM is unavailable.
    """
    metric   = intent.get("metric", "count")
    data     = result.get("data", [])
    x_field  = result.get("x_field", "category")
    y_field  = result.get("y_field", "value")
    ml       = result.get("metric_label", "Value")
    rl       = result.get("result_label", "Analysis")

    if not data:
        return {
            "headline": "No data available for this query.",
            "bullets":  ["The analysis returned no results. Check your filters or query."],
            "so_what":  "Review the dataset and try a broader query.",
            "data_caveat": None,
        }

    # compute summary stats from result
    values = []
    for row in data:
        try:
            values.append(float(row[y_field]))
        except (TypeError, ValueError, KeyError):
            pass

    if not values:
        return {
            "headline": f"{rl} — no numeric values to summarise.",
            "bullets":  ["Values could not be parsed for insight generation."],
            "so_what":  "Verify the metric column contains numeric data.",
            "data_caveat": None,
        }

    total      = sum(values)
    avg        = total / len(values)
    top_row    = data[0]
    bottom_row = data[-1]

    top_x  = str(top_row.get(x_field, "Unknown"))
    top_y  = _format_value(top_row.get(y_field), metric)
    bot_x  = str(bottom_row.get(x_field, "Unknown"))
    bot_y  = _format_value(bottom_row.get(y_field), metric)
    avg_f  = _format_value(avg, metric)

    # top/bottom ratio
    try:
        ratio = float(top_row.get(y_field, 0)) / float(bottom_row.get(y_field, 1))
        ratio_str = f"{ratio:.1f}x"
    except (ZeroDivisionError, TypeError, ValueError):
        ratio_str = "significantly"

    bullets = [
        f"**{top_x}** leads with {top_y} {ml.lower()} — "
        f"the highest in the dataset.",
        f"**{bot_x}** is the weakest at {bot_y}, "
        f"compared to an average of {avg_f} across all categories.",
        f"The gap between top and bottom is **{ratio_str}** — "
        f"{'a major disparity worth investigating.' if ratio_str != 'significantly' else 'significant.'}",
    ]

    # add a 4th bullet for rate metrics
    if metric == "rate" and len(data) >= 3:
        mid_row = data[len(data) // 2]
        mid_x   = str(mid_row.get(x_field, ""))
        mid_y   = _format_value(mid_row.get(y_field), metric)
        bullets.append(
            f"Mid-tier: **{mid_x}** at {mid_y}. "
            f"Focus efforts on high-performing segments to maximise ROI."
        )

    question_type = intent.get("question_type", "analysis")
    action_verbs  = {
        "ranking":      "Prioritise",
        "comparison":   "Focus on",
        "distribution": "Investigate",
        "trend":        "Monitor",
        "aggregation":  "Track",
    }
    verb = action_verbs.get(question_type, "Investigate")

    return {
        "headline": f"**{top_x}** shows the highest {ml.lower()} at {top_y}.",
        "bullets":  bullets,
        "so_what":  f"{verb} **{top_x}** and similar high-performing categories "
                    f"to leverage the {ratio_str} advantage over the weakest segment.",
        "data_caveat": None,
    }


# ── public API ────────────────────────────────────────────────────

def narrate_insights(
    query_intent:     dict[str, Any],
    execution_result: dict[str, Any],
    viz_spec:         dict[str, Any],
) -> dict[str, Any]:
    """
    Main entry point.
    Returns an InsightReport dict:
    {
        "headline": str,
        "bullets": list[str],
        "so_what": str,
        "data_caveat": str | None,
        "_source": "llm" | "template"
    }
    """
    if _llm_available() and execution_result.get("success") and execution_result.get("data"):
        msg = _build_narrator_message(query_intent, execution_result)
        raw = _call_llm(_NARRATOR_SYSTEM, msg)
        if raw:
            try:
                cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
                report  = json.loads(cleaned)
                report["_source"] = "llm"
                # ensure bullets is always a list
                if isinstance(report.get("bullets"), str):
                    report["bullets"] = [report["bullets"]]
                return report
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Narrator LLM JSON parse failed: %s", exc)

    logger.info("Using template-based narration.")
    report = _template_narrate(query_intent, execution_result)
    report["_source"] = "template"
    return report