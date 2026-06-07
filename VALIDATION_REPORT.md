# LangGraph Regression Fix Validation Report

## Root Cause

- The LangGraph graph routed collection QA exhaustion to `mark_collection_degraded -> fail_run`.
- The legacy Orchestrator marked `qa_collection.degraded = True` after max retries, then continued to dimension generation, parallel analysis, analysis QA, strategy generation, and strategy QA.
- Because `fail_run` creates an empty `StrategyReport` when strategy has not run, `main.py` then exported a normal-looking HTML/JSON report with `competitor_count=0`.
- The regression was not in the HTML template. It was caused by non-equivalent graph routing plus unconditional success report export.

## Modified Files

- `workflow/graph.py`
  - Added routing after collection degradation.
  - Collection QA exhaustion now continues to `generate_dimensions` when valid collection data exists.
  - Analysis QA exhaustion now degrades and continues to `generate_strategy`.
  - Strategy QA exhaustion now degrades and continues to `finalize_report`.
  - Preserved hard failure routing when collection data is missing.
- `workflow/nodes.py`
  - Preserves the last valid `competitors_data` and `original_search_texts` if a retry returns an empty result.
- `core/orchestrator.py`
  - Stores the final LangGraph state/status for entrypoint-level failure handling.
- `main.py`
  - Stops exporting normal success HTML/JSON when the LangGraph workflow status is `failed`.
- `tests/test_orchestrator_baseline.py`
  - Added fixture citations and citation-index behavior for HTML/source regression tests.
- `tests/test_workflow_graph.py`
  - Added and updated regression tests for collection degraded continuation, hard failure, analysis degraded continuation, strategy degraded continuation, state/citation preservation, HTML structure, and parallel overlap.
- `tests/test_orchestrator_facade.py`
  - Added a test that `main.run_analysis()` does not export success HTML/JSON for failed graph runs.
- `PLAN.md`
  - Added the regression diagnosis and repair plan.

## Test Commands And Results

### Static Patch Check

Command:

```powershell
git diff --check
```

Result:

```text
passed
```

### Mock Unit Tests

Command:

```powershell
powershell -NoProfile -Command "& 'D:\Elmo\anaconda3\Scripts\conda.exe' run -n smartcomp-engine-dev python -m unittest discover tests"
```

Result:

```text
Ran 29 tests in 1.591s
OK
```

Status: passed. The direct `conda` command was unavailable in the sandbox, but the already-approved PowerShell command successfully ran the same test suite through `D:\Elmo\anaconda3\Scripts\conda.exe`.

### Fallback Smoke Test

Command:

```powershell
powershell -NoProfile -Command "& 'D:\Elmo\anaconda3\Scripts\conda.exe' run -n smartcomp-engine-dev --no-capture-output python main.py --rule '飞书'"
```

Result:

```text
exit code 0
run: output/runs/20260607_050223_飞书
run_meta.status: completed
run_meta.competitor_count: 3
timings include: dimension, parallel_analysis, qa_analysis, strategy, qa_strategy, total
report.html header: 分析竞品 3 个
```

Status: passed. The fallback report contains target product intro, discovered competitors, feature matrix, pricing analysis, market analysis, strategy section, and no `分析竞品 0 个` header.

### Real API Validation

Command:

```powershell
powershell -NoProfile -Command "& 'D:\Elmo\anaconda3\Scripts\conda.exe' run -n smartcomp-engine-dev --no-capture-output python main.py '飞书'"
```

Result:

```text
exit code 0
run: output/runs/20260607_050246_飞书
run_meta.status: completed_degraded
run_meta.competitor_count: 5
qa_collection attempt 3: degraded=true
pricing QA attempt 3: degraded=true
timings include: dimension, market_analysis, pricing_analysis, product_analysis, parallel_analysis, qa_analysis, strategy, qa_strategy, total
output files include: 03_dimension_config.json, 04_product_analysis.json, 05_pricing_analysis.json, 06_market_analysis.json, 07_strategy_report.json, report.html, report.json
report.html header: 分析竞品 5 个
data sources: 89 citations
```

Status: passed. The real API run exercised the original regression path: collection QA exhausted retries and degraded, then continued into dimension, parallel analysis, analysis QA, strategy, and strategy QA. No API key was printed or inspected.

Observed successful real API evidence:

- `run_meta.json` status is `completed_degraded`.
- `competitor_count` is 5.
- timings include `dimension`, `parallel_analysis`, `qa_analysis`, `strategy`, `qa_strategy`, and `total`.
- `03_dimension_config.json`, `04_product_analysis.json`, `05_pricing_analysis.json`, `06_market_analysis.json`, and `07_strategy_report.json` exist.
- `report.html` is not an empty shell and shows `分析竞品 5 个`.

## Behavior Covered By Added Tests

- Collection QA passes normally and the graph completes.
- Collection QA fails once, retries with feedback, preserves competitor data and citations, then completes.
- Collection QA exhausts retries, marks degraded, preserves valid collected data, continues to dimension and all downstream nodes, and produces a non-empty degraded report.
- Collection QA exhausts retries with no usable collection data, enters `fail_run`, and does not produce a normal strategy artifact.
- Product analysis QA exhaustion degrades and continues to strategy instead of failing.
- Strategy QA exhaustion degrades and finalizes instead of failing.
- Product, pricing, and market analysis still run concurrently with overlapping execution windows.
- HTML output generated from valid state contains the expected fixture content and source URL.
- `main.run_analysis()` does not save success HTML/JSON when the graph status is `failed`.

## Rollback Path

- The legacy orchestrator remains available via `USE_LANGGRAPH_WORKFLOW=0`, `false`, `no`, or `off`.
- No existing Agent, prompt-loading behavior, Doubao client, or rule-engine fallback path was removed.

## Remaining Risks

- The real API run still ended as `completed_degraded` because collection and pricing QA exhausted retries. This is expected under the legacy-compatible degraded-continuation behavior, but the content quality issues identified by QualityAgent remain product/LLM-output risks.
- The real API run took about 47 minutes, so repeated end-to-end validation is expensive.
- The validation did not inspect API secrets and did not print API keys.
