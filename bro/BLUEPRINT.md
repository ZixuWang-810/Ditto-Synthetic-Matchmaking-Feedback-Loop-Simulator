# Blueprint — Issue #12

**Objective**: Got this error log when run the conversation simulation in UI:
**Updated**: 2026-03-17T16:45:05.668082+00:00
**Tasks**: 4 (4/4 completed)

---

## [x] Task 1: Add a `repair_json()` function and integrate it into `generate_structured()` in `src/llm/client.py`.

**What to build:**

1. Add a module-level `repair_json(raw: str) -> Optional[dict]` function (place it ABOVE the `LLMClient` class) that fixes common LLM JSON issues:
   - Strip markdown code fences (`\`\`\`json ... \`\`\``) and extract the JSON object
   - Fix trailing commas before `]` or `}` using `re.sub(r',\s*([}\]])', r'\1', text)`
   - Fix unescaped double quotes inside string values (the root cause of this bug — `5'5"` produces an unescaped `"` mid-string). Strategy: after finding the JSON object boundaries, use a character-by-character state machine that tracks whether we're inside a JSON string. When it detects a `"` that is NOT preceded by `\` and is NOT a structural string delimiter (i.e., it's followed by characters that don't match `: `, `,`, `}`, `]`, or whitespace+any of those), escape it to `\"`.
   - Close unclosed brackets/braces: count `{`, `}`, `[`, `]` and append missing closers
   - After all repairs, attempt `json.loads(text)` — return the dict on success, `None` on failure

2. Modify the existing `generate_structured()` method to add a repair-then-retry pipeline when `model_validate_json()` fails:
   - **Current behavior** (around line 120-130): catches the parse exception and immediately raises `ValueError`
   - **New behavior**: On initial parse failure:
     a. Call `repair_json(raw_text)` on the raw LLM response
     b. If repair returns a dict, call `response_model.model_validate(repaired_dict)` and return it
     c. If repair fails or validation fails, retry the LLM call ONCE with the original messages plus an assistant message containing the broken response and a user message: `"Your previous response had invalid JSON. Return ONLY valid JSON matching the schema. No extra text."` — use temperature 0.2 for the retry
     d. On the retry response, attempt `model_validate_json()` → if fails, attempt `repair_json()` + `model_validate()` → if still fails, raise the original `ValueError` (preserving the raw text in the error message for debugging)
   - Log each step at `logger.warning` level so operators can see repair/retry activity

**Key constraint:** The method signature of `generate_structured()` must NOT change — same parameters, same return type, same `ValueError` on final failure. This is purely internal resilience.

**Reference:** The skill `.tmb/skills/llm-json-repair.md` has the full `repair_json` implementation pattern including `_fix_unescaped_inner_quotes` and `_close_brackets` helpers. The skill `.tmb/skills/ollama-raw-client-structured-output.md` has the retry pattern. Adapt these to fit the existing code structure in `client.py`.

- **Tools**: file_read, file_write
- **Success criteria**: Running `uv run python -c "from src.llm.client import repair_json; r = repair_json('{\"score\": 0.65, \"justification\": \"test\", \"shared_interests\": [\"a\"], \"potential_issues\": [\"height difference (5\\x275\\x22\"]}'); print(r)"` prints a valid dict with all 4 keys. Also: `uv run python -c "from src.llm.client import repair_json; r = repair_json('{\"a\": 1, \"b\": [1, 2,'); print(r)"` prints `{'a': 1, 'b': [1, 2]}` (closed brackets, removed trailing comma). The `generate_structured` method signature is unchanged.
- **Status**: completed

## [x] Task 2: Add a try/except fallback in `MatchScorer._llm_compatibility_score()` in `src/ditto_bot/matcher.py` so that if `generate_structured()` raises `ValueError` (after all repair+retry attempts), the method returns a neutral `CompatibilityScore` instead of crashing the simulation.

**What to change:**

In the `_llm_compatibility_score` method (around line 220-255 in `matcher.py`), wrap the existing `self.client.generate_structured(...)` call in a try/except block:

```python
try:
    return self.client.generate_structured(
        prompt=prompt,
        response_model=CompatibilityScore,
        temperature=0.3,
    )
except (ValueError, Exception) as e:
    logger.warning(
        "LLM compatibility scoring failed for %s vs %s: %s",
        user.name, candidate.name, e,
    )
    return CompatibilityScore(
        score=0.5,
        justification="LLM scoring unavailable — using neutral fallback score",
        shared_interests=[],
        potential_issues=["scoring_unavailable"],
    )
```

**Key design decisions:**
- Catch at the per-candidate level (`_llm_compatibility_score`), NOT at `score_candidates` level — one failed candidate shouldn't block scoring of others
- Use 0.5 as the neutral score (midpoint — won't surface as top match but won't exclude)
- Include `"scoring_unavailable"` in `potential_issues` so downstream code can detect fallback scores
- Log at WARNING level with both persona names and the exception for debugging

**Reference:** The skill `.tmb/skills/matcher-fallback-pattern.md` has the exact pattern.

- **Tools**: file_read, file_write
- **Success criteria**: Running `uv run python -c "from src.ditto_bot.matcher import CompatibilityScore; cs = CompatibilityScore(score=0.5, justification='LLM scoring unavailable — using neutral fallback score', shared_interests=[], potential_issues=['scoring_unavailable']); print(cs.model_dump_json())"` succeeds. Inspecting `src/ditto_bot/matcher.py` shows a try/except around the `generate_structured` call in `_llm_compatibility_score` that catches `ValueError` and returns a neutral `CompatibilityScore(score=0.5, ...)`.
- **Status**: completed

## [x] Task 3: Write a focused test in `tests/test_json_repair.py` that validates the repair_json function handles the exact failure modes from the bug report, plus edge cases.

**Test cases to cover:**

1. **The exact bug** — the raw response from the error log: `'{\n  "score": 0.65,\n  "justification": "Date types align as both are looking for serious relationships, shared interests include photography and cooking, but Juan\'s casual all-nighter habits may clash with Emily\'s need for a partner who appreciates her studious nature.",\n  "shared_interests": [\n    "photography",\n    "cooking"\n  ],\n  "potential_issues": [\n    "different study habits",\n    "height difference (5\'5"'` — repair should produce a valid dict with score 0.65

2. **Truncated output** — JSON cut off mid-value with unclosed brackets: `'{"score": 0.7, "justification": "good match", "shared_interests": ["hiking"'` → should close brackets and parse

3. **Trailing comma** — `'{"score": 0.8, "items": ["a", "b",]}'` → should remove trailing comma and parse

4. **Markdown fences** — `` '```json\n{"score": 0.5}\n```' `` → should extract and parse

5. **Already valid JSON** — `'{"score": 0.9, "justification": "great"}'` → should return as-is

6. **Completely unparseable** — `'I cannot generate JSON'` → should return None

7. **Test the matcher fallback** — mock `LLMClient.generate_structured` to raise `ValueError`, call `MatchScorer._llm_compatibility_score()`, assert it returns a `CompatibilityScore` with `score=0.5` and `"scoring_unavailable"` in `potential_issues`

Use `pytest` with `unittest.mock.patch` for the matcher fallback test. Import `repair_json` from `src.llm.client` and `MatchScorer`/`CompatibilityScore` from `src.ditto_bot.matcher`.

- **Tools**: file_write, file_read
- **Success criteria**: Running `uv run pytest tests/test_json_repair.py -v` passes all 7+ test cases with 0 failures.
- **Status**: completed

## [x] Task 4: Update `README.md` at the project root to document the JSON repair and fallback resilience added in this issue.

**What to add** (append a new section, do NOT overwrite existing content):

Add a section titled `## LLM Output Resilience` (place it after the existing `## LangGraph Architecture` section) that explains:

1. **Problem**: Local LLMs (especially smaller models like llama3.2) can produce malformed JSON — unescaped quotes inside strings (e.g., `5'5"`), truncated output from token limits, trailing commas
2. **3-Layer Defense**:
   - Layer 1: `repair_json()` in `src/llm/client.py` — fixes unescaped inner quotes, closes unclosed brackets, strips trailing commas, extracts JSON from markdown fences
   - Layer 2: Retry with nudge — if repair fails, retries the LLM call once with a corrective prompt at lower temperature
   - Layer 3: Neutral fallback in `src/ditto_bot/matcher.py` — if all parsing attempts fail, returns a neutral `CompatibilityScore(score=0.5)` so the simulation continues
3. **Observability**: All repair/retry/fallback events are logged at WARNING level. Fallback scores include `"scoring_unavailable"` in `potential_issues` for downstream detection.

Keep the section concise (15-25 lines of markdown). Match the existing README's tone and formatting style.

- **Tools**: file_read, file_write
- **Success criteria**: The file `README.md` contains a section titled `## LLM Output Resilience` that describes the 3-layer defense (repair, retry, fallback). The rest of the existing README content is preserved unchanged.
- **Status**: completed
