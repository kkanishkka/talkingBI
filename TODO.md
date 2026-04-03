# TalkingBI Refactor TODO

## Approved Plan Steps

✅ **Step 0**: Created this TODO.md

**Step 1**: Fix table listing + ranking ✅
- [x] Updated `backend/app/layers/ingestion/datasources/supabase.py` → `list_tables()` include views via information_schema
- [x] Updated `backend/app/api/routes/connect.py` → add metadata (rows, cols, type) + analytical tags
- [x] Fixed `get_table_schema` and `load_dataframe` to support views

**Step 2**: Replace App.jsx JSON dump with dashboard ✅
- [x] Imported components
- [x] Table dropdown with metadata
- [x] Full dashboard rendering (no JSON), LoadingSpinner

**Step 3**: Improve query understanding mapping ✅
- [x] Added business term mapping in `_match_columns()` ("category" → "category_name", etc.)

**Step 4**: Validation & Completion ✅
- [x] All changes implemented
- Run: 
  - Backend: `cd backend && uvicorn app.main:app --reload`
  - Frontend: `cd frontend && npm run dev`
- Test cases:
  1. Connect Supabase → verify `vw_order_details`, `raw_orders` prioritized with ⭐
  2. Select table → ask "top 5 categories by amount" → dashboard (summary + charts)
  3. "count by payment mode", "top subcategories"
  4. No raw JSON, proper loading/errors

## Current Progress
Ready for Step 1

