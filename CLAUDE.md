# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow

**Always use plan mode** before any non-trivial implementation task (adding features, modifying existing behavior, touching more than 2–3 files). Use `EnterPlanMode` to explore the codebase, design an approach, and get user approval before writing or modifying code. Single-line fixes and typo corrections do not require plan mode.

## Project Overview

Project Dolly is a Streamlit web app that reads multi-regional Google Sheets account planning data, applies strategic scoring logic, generates AI-voiced CRO comments via Claude, and enables a human-in-the-loop review workflow with write-back to Google Sheets.

## Commands

```bash
streamlit run app.py                        # Run the app
python -m src.ingestion.tone_scraper        # Regenerate CRO tone calibration
python -m py_compile src/scoring/composite.py  # Syntax check without running
```

No test suite is currently configured (`tests/` is empty).

## Credentials Setup

Set `GOOGLE_SERVICE_ACCOUNT_JSON` and `ANTHROPIC_API_KEY` via `.streamlit/secrets.toml`, environment variables, or `credentials/service_account.json` — tried in that order by `src/google/auth.py`.

Google Drive folder IDs and regional file patterns are configured in `config/regions.yaml`.

## Architecture

### Data Flow

```
Google Drive
    ↓
drive_client.py  — discovers regional spreadsheets by fnmatch pattern (config/regions.yaml)
    ↓
sheets_client.py — loads Maps, Tech Stake, Summary tabs as DataFrames
    ↓
normalizer.py    — fuzzy-matches variant column names to canonical names (column_mappings.yaml)
joiner.py        — left-joins 3 tabs per region on account_name; adds region + spreadsheet_id
    ↓
scoring/engine.py — orchestrates three independent sub-scorers:
  nrr_scorer.py       → risk score 0–100, tier (CRITICAL/AT_RISK/HEALTHY/STRONG)
  threading_scorer.py → risk score 0–100, tier (SINGLE/DUAL/MULTI)
  expansion_scorer.py → opportunity score 0–100, tier (HIGH/MEDIUM/LOW)
    ↓
composite.py — NRR (50%) + threading (25%) + expansion (25%) → composite score
             — P1 ≥ 65 | P2 40–64 | P3 < 40
             — Hard overrides: NRR CRITICAL, renewal < 90 days, health ≤ 2 → force P1
    ↓  [cached 30 min via @st.cache_data]
Streamlit UI (app.py → pages/)
  Review tab   — one-account-at-a-time card; generate/edit/approve CRO comment
  Dashboard tab — P1/P2/P3 counts, regional breakdown, NRR distribution
  Report tab   — generate + download Markdown executive report
    ↓
Claude API (src/llm/) — comment generation with exponential-backoff retry
    ↓
user approve/edit/regenerate → auto-save JSON session
    ↓
optional Sheets write-back — approved comments routed to original spreadsheet_id per account
```

### Scoring Engine (`src/scoring/`)

All thresholds and weights live in `config/scoring_weights.yaml`.

- **NRR scorer**: Handles multiple input formats and auto-converts MRR growth rates.
- **Threading scorer**: Parses contact count from integers, name lists, or comma/semicolon-separated strings.
- **Expansion scorer**: Scans 16 product channels; awards whitespace (+5) and competitor (+8) points plus bonuses for low Insider penetration and zero-product accounts.
- **Composite**: Each account gets a `primary_signal` explanation (what drove the tier assignment).

### LLM Integration (`src/llm/`)

- Model: `claude-sonnet-4-6` or `claude-opus-4-6` (user-selectable in UI via sidebar).
- Prompt templates are YAML-based (`config/prompt_templates.yaml`), not hardcoded.
- System prompt = CRO persona (`config/cro_persona.yaml`) + voice rules + few-shot tone examples.
- User prompt = account data (financials, strategy, tech stake, risk scores) + instructions.
- `client.py` retries up to 3 times with exponential backoff on transient API errors.

### Session Management (`src/session/`)

- `SessionState` + `AccountDecision` dataclasses track review order and per-account decisions.
- Auto-saved to `data/sessions/session_YYYYMMDD_HHMMSS.json` after each decision.
- Sessions are resumable — load a previous JSON from the sidebar to continue where you left off.

### Configuration vs. Code

Anything a CRO (non-engineer) might want to tune lives in `config/*.yaml`:

| File | Controls |
|---|---|
| `regions.yaml` | Drive folder ID, file patterns, sheet type keywords, write-back tab |
| `scoring_weights.yaml` | NRR/threading/expansion thresholds, P-tier cutoffs, hard override rules |
| `column_mappings.yaml` | Column name aliases, channel definitions, insider/whitespace/competitor markers |
| `cro_persona.yaml` | CRO name, title, philosophy paragraph, voice rules |
| `prompt_templates.yaml` | System + user prompt templates with `{placeholder}` variables |
| `cro_tone_profile.yaml` | **Auto-generated** by `tone_scraper.py` — do not edit manually |
