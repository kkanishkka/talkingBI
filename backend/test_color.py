import sys
# add backend dir to path
sys.path.append('c:\\Users\\minak\\OneDrive\\Desktop\\Talking_BI\\backend')

from app.services.query_understanding_agent import understand_query

schema = {
    "columns": [
        {"name": "sales", "role": "metric", "semantic_hint": "currency", "dtype": "float", "unique_count": 100},
        {"name": "region", "role": "dimension", "dtype": "string", "unique_count": 5}
    ]
}

intent1 = understand_query("Show me total sales by region in a dark theme", schema)
intent2 = understand_query("Show me total sales by region in a pastel palette", schema)
intent3 = understand_query("Show me total sales by region", schema)


print(f"Intent1 color: {intent1.color_schema}")
print(f"Intent2 color: {intent2.color_schema}")
print(f"Intent3 color: {intent3.color_schema}")
