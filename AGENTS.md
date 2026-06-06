# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

SmartComp_Engine is a multi-agent competitor analysis system. Given a product name, it discovers competitors via web search, analyzes them across three dimensions (features, pricing, market position), and generates an HTML/JSON strategy report. All LLM calls go through the Doubao (Volcengine) API. Every agent has a rule-engine fallback for zero-cost operation without LLM access.

## Running

```bash
conda create -n smartcomp python=3.12 -y && conda activate smartcomp
pip install -r requirements.txt

python3 main.py "product_name"           # LLM mode (requires .env with DOUBAO_API_KEY)
python3 main.py --rule "product_name"    # Rule engine mode (no API key needed)
python3 main.py --count 5 "product_name" # Set competitor count (3-8)
```

Reports are saved to `output/` as `{product}_analysis_report.{html,json}`.

## Configuration

All config is in `.env` (custom loader in `config.py`, no python-dotenv). Key vars: `DOUBAO_API_KEY`, `DOUBAO_MODEL` (endpoint ID), `DOUBAO_BASE_URL`. The `.env` file is gitignored — never commit it.

## Architecture

### Pipeline (orchestrated by `core/orchestrator.py`)

```
Phase 1   DiscoveryAgent    → CompetitorList          (serial, 2 LLM calls)
Phase 2   CollectionAgent   → dict[name, CompetitorData] (serial, 1+N calls)
Phase 2.5 DimensionAgent    → DimensionConfig          (serial, 1 call)
Phase 3   ProductAgent + PricingAgent + MarketAgent    (parallel via asyncio.gather, 3 calls)
Phase 4   StrategyAgent     → StrategyReport + HTML    (serial, 1 call)
```

Total LLM calls: 6 + N (N = number of competitors).

### Agent pattern

All agents extend `BaseAgent` (`agents/base_agent.py`), which provides `ask_llm()`, `ask_llm_json()`, citation utilities, and an abstract `run()`. Each agent implements both an LLM path and a keyword/template rule-engine fallback.

### Prompt system

Prompts live in `prompts/*.md`. Each file is split by `## section_name` headers — a required `system_prompt` section plus named template sections with `{placeholder}` format strings. Loaded and cached by `core/prompt_loader.py`.

### LLM and search clients

- `core/llm_client.py` — Doubao OpenAI-compatible chat completions. 2 retries, 300s timeout, JSON extraction from responses (tries direct parse, then regex for code blocks, then brace matching).
- `core/search_client.py` — Doubao Responses API with `web_search` tool. Single and batch search with configurable delay.

### Data models

All domain types are dataclasses in `models/domain.py`: Citation, CompetitorList, CompetitorData, DimensionConfig, ProductAnalysis, PricingAnalysis, MarketAnalysis, StrategyReport.

### Report generation

`StrategyAgent.format_html_report()` (in `agents/strategy_agent.py`) produces a standalone HTML page with inline CSS — competitor cards, feature matrix, pricing table, market share bars, action plan, and citation appendix.

## Adding a new agent

1. Create `agents/new_agent.py` extending `BaseAgent`
2. Create `prompts/new_agent.md` with `## system_prompt` and template sections
3. Add agent instantiation and pipeline wiring in `core/orchestrator.py`
4. Add corresponding data model in `models/domain.py` if needed
