from __future__ import annotations

from typing import Any


def _make_chart_block(chart: dict[str, Any], x: int, y: int, w: int, h: int) -> dict[str, Any]:
    return {
        "chart_title": chart["title"],
        "chart_type": chart["chart_type"],
        "fields": chart["fields"],
        "position": {"x": x, "y": y, "w": w, "h": h},
        "what_it_shows": chart.get("what_it_shows"),
        "why_this_chart": chart.get("why_this_chart"),
    }


def generate_layouts(charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # keep first 4 charts for MVP
    charts = charts[:4]

    executive_layout = {
        "layout_id": "layout_1",
        "layout_name": "Executive Overview",
        "rationale": "Prioritizes a quick top-level understanding with a clean summary-first dashboard structure.",
        "sections": {
            "header": {"title": "Executive Overview Dashboard"},
            "summary_panel": {"position": "top-right"},
            "kpi_panel": {"position": "top-left"},
            "chart_blocks": [
                _make_chart_block(charts[0], 0, 1, 6, 4) if len(charts) > 0 else None,
                _make_chart_block(charts[1], 6, 1, 6, 4) if len(charts) > 1 else None,
                _make_chart_block(charts[2], 0, 5, 6, 4) if len(charts) > 2 else None,
                _make_chart_block(charts[3], 6, 5, 6, 4) if len(charts) > 3 else None,
            ],
        },
    }

    analytical_layout = {
        "layout_id": "layout_2",
        "layout_name": "Analytical Deep Dive",
        "rationale": "Provides a balanced grid for users who want to compare multiple views in detail.",
        "sections": {
            "header": {"title": "Analytical Deep Dive Dashboard"},
            "summary_panel": {"position": "bottom"},
            "kpi_panel": {"position": "top"},
            "chart_blocks": [
                _make_chart_block(charts[0], 0, 1, 12, 4) if len(charts) > 0 else None,
                _make_chart_block(charts[1], 0, 5, 6, 4) if len(charts) > 1 else None,
                _make_chart_block(charts[2], 6, 5, 6, 4) if len(charts) > 2 else None,
                _make_chart_block(charts[3], 0, 9, 12, 4) if len(charts) > 3 else None,
            ],
        },
    }

    comparison_layout = {
        "layout_id": "layout_3",
        "layout_name": "Comparison Focus",
        "rationale": "Highlights side-by-side category comparisons for fast comparative analysis.",
        "sections": {
            "header": {"title": "Comparison Focus Dashboard"},
            "summary_panel": {"position": "right"},
            "kpi_panel": {"position": "top"},
            "chart_blocks": [
                _make_chart_block(charts[0], 0, 1, 6, 5) if len(charts) > 0 else None,
                _make_chart_block(charts[2], 6, 1, 6, 5) if len(charts) > 2 else None,
                _make_chart_block(charts[3], 0, 6, 12, 4) if len(charts) > 3 else None,
                _make_chart_block(charts[1], 0, 10, 12, 3) if len(charts) > 1 else None,
            ],
        },
    }

    monitoring_layout = {
        "layout_id": "layout_4",
        "layout_name": "Monitoring / Operations",
        "rationale": "Designed like an operational dashboard with KPI-first scanning and compact visuals.",
        "sections": {
            "header": {"title": "Monitoring / Operations Dashboard"},
            "summary_panel": {"position": "bottom-right"},
            "kpi_panel": {"position": "top"},
            "chart_blocks": [
                _make_chart_block(charts[1], 0, 1, 12, 3) if len(charts) > 1 else None,
                _make_chart_block(charts[0], 0, 4, 6, 4) if len(charts) > 0 else None,
                _make_chart_block(charts[2], 6, 4, 6, 4) if len(charts) > 2 else None,
                _make_chart_block(charts[3], 0, 8, 12, 4) if len(charts) > 3 else None,
            ],
        },
    }

    layouts = [executive_layout, analytical_layout, comparison_layout, monitoring_layout]

    # remove None blocks
    for layout in layouts:
        layout["sections"]["chart_blocks"] = [
            block for block in layout["sections"]["chart_blocks"] if block is not None
        ]

    return layouts