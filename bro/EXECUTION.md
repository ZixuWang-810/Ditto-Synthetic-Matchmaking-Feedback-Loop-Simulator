# Execution Plan — Issue #12

**Objective**: Got this error log when run the conversation simulation in UI:
ValueError: Failed to parse structured output: 1 validati

---

## Task 1
Add a `repair_json()` function and integrate it into `generate_structured()` in `src/llm/client.py`.

**What to…

## Task 2
Add a try/except fallback in `MatchScorer._llm_compatibility_score()` in `src/ditto_bot/matcher.py` so that if…

## Task 3
Write a focused test in `tests/test_json_repair.py` that validates the repair_json function handles the exact failure…

## Task 4
Update `README.md` at the project root to document the JSON repair and fallback resilience added in this…

