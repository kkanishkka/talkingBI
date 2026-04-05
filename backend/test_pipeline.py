import sys
import os
sys.path.append('c:\\Users\\minak\\OneDrive\\Desktop\\Talking_BI\\backend')

from app.core.models import SchemaContext, ColumnProfile, ColumnRole, SemanticHint
from app.services.schema_profiler import build_schema_context
from app.core.llm_client import llm_client

print(f"Testing LLM Client on Groq model: {llm_client._groq_model}")

schema_prof = {
    "dataset_summary": {
        "rows": 100,
        "columns": 3,
        "column_names": ["sales", "category", "price_text"]
    },
    "columns": [
        {
            "name": "sales", "role": "metric", "dtype": "float",
            "semantic_hint": "currency", "unique_count": 50
        },
        {
            "name": "category", "role": "dimension", "dtype": "string",
            "semantic_hint": "category_key", "unique_count": 5
        },
        {
            "name": "price_text", "role": "dimension", "dtype": "string",
            "semantic_hint": "none", "unique_count": 20
        }
    ]
}

# 1. Test LLM Planner integration
try:
    from app.services.query_understanding_agent import understand_query
    from app.services.planner import plan_dashboard
    
    intent = understand_query("give me a dashboard of sales with respect to category", schema_prof)
    print("Intent metrics:", intent.metric)
    print("Intent target:", intent.target_variable)

    plan = plan_dashboard(intent, schema_prof)
    print("Dashboard:", plan.is_dashboard)
    print("KPIs:", len(plan.kpi_definitions))
    print("Charts:", len(plan.sub_plans))

except Exception as e:
    print(f"Pipeline Test failed: {e}")
