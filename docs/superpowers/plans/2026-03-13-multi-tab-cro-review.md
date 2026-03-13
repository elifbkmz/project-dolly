# Multi-Tab CRO Review Flow Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a three-step CRO review workflow — Portfolio Summary (Overview tab), Account Reviews (Maps tab), and Tech Stack Reviews (Current Tech Stack Information tab) — each with CRO-voiced comment generation and write-back to the corresponding Google Sheet tab.

**Architecture:** The review page gains a step indicator (1→2→3) controlling which UI phase renders. Step 1 aggregates portfolio metrics from `scored_df` and generates one regional CRO comment written back to the Overview tab. Step 2 is the existing account-by-account review (enhanced with ARR>$5K sorting). Step 3 filters accounts with vendor gaps, generates tech-stake-specific CRO comments, and writes back to the Current Tech Stack Information tab. Each step uses its own prompt template and write-back target.

**Tech Stack:** Python 3.11+, Streamlit, Google Sheets API v4, Anthropic Claude API, pandas, PyYAML

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `src/llm/portfolio_comment.py` | Aggregate portfolio metrics from scored_df, build portfolio prompt, generate CRO comment |
| `src/llm/tech_stake_comment.py` | Identify vendor gaps per account, build tech stake prompt, generate CRO comment |
| `tests/test_portfolio_comment.py` | Tests for portfolio metric aggregation and prompt building |
| `tests/test_tech_stake_comment.py` | Tests for gap detection and prompt building |

### Modified files
| File | Changes |
|------|---------|
| `config/regions.yaml` | Add `comment_write_tabs` dict mapping step → tab name |
| `config/prompt_templates.yaml` | Add `portfolio_prompt_template` and `tech_stake_prompt_template` |
| `src/session/state.py` | Add `review_step` field to `SessionState`, `comment_type` to `AccountDecision` |
| `src/google/sheets_client.py` | Add `write_portfolio_comment()` for single-cell Overview write-back |
| `pages/review.py` | Three-step flow: step indicator, portfolio summary UI, tech stake review UI, multi-tab save |

---

## Chunk 1: Backend — Config, Generators, Write-back

### Task 1: Config updates

**Files:**
- Modify: `config/regions.yaml:52-55`
- Modify: `config/prompt_templates.yaml:59-69`

- [ ] **Step 1: Update regions.yaml with multi-tab write-back config**

Replace the single `comment_write_tab` with a `comment_write_tabs` dict:

```yaml
# Tab where CRO-approved comments are written back, per review step.
comment_write_tabs:
  portfolio: "Overview"
  accounts: "Maps"
  tech_stake: "Current Tech Stake Information"

# Keep legacy key for backward compatibility
comment_write_tab: "Maps"
```

- [ ] **Step 2: Add portfolio prompt template to prompt_templates.yaml**

Append after the `tone_calibration_header` block (after line 61):

```yaml
portfolio_prompt_template: |
  Review this regional portfolio and write your {sentence_count}-sentence CRO comment
  for the Overview tab.

  REGION: {region}

  PORTFOLIO SUMMARY:
  - Total Accounts: {total_accounts}
  - Total ARR: {total_arr}
  - Average NRR: {avg_nrr}
  - P1 (Critical): {p1_count} accounts
  - P2 (At-Risk): {p2_count} accounts
  - P3 (Healthy): {p3_count} accounts

  NRR RISK DISTRIBUTION:
  - CRITICAL (NRR < 90%): {nrr_critical_count} accounts
  - AT_RISK (90-100%): {nrr_at_risk_count} accounts
  - HEALTHY (100-110%): {nrr_healthy_count} accounts
  - STRONG (>110%): {nrr_strong_count} accounts

  TOP 5 PRIORITY ACCOUNTS (by composite score):
  {top_5_accounts}

  UPCOMING RENEWALS (next 90 days):
  {upcoming_renewals}

  EXPANSION OPPORTUNITY:
  - Accounts with competitor-held channels: {competitor_opportunity_count}
  - Accounts with whitespace channels: {whitespace_opportunity_count}
  - Total displacement opportunities: {displacement_count}

  Write your CRO portfolio comment now. Address the biggest risk or opportunity
  at the regional level. Be specific about which accounts or patterns need attention.
  Do not use bullet points or headers. Output only the comment text, nothing else.

tech_stake_prompt_template: |
  Review this account's tech stack and write your {sentence_count}-sentence CRO comment
  for the Current Tech Stack Information tab.

  ACCOUNT: {account_name}
  REGION: {region}
  AE: {ae_name}
  ARR: {arr_display}
  NRR: {nrr_display}

  TECH STACK STATUS:
  - Insider Products Active: {insider_product_count} of {total_channels} channels
  - Active Insider Products: {insider_channels_display}

  VENDOR GAPS (displacement opportunities):
  {vendor_gaps}

  WHITESPACE (uncaptured channels):
  {whitespace_gaps}

  CO-EXISTING COMPETITORS: {coexisting_competitors}

  Write your CRO tech stack comment now. Focus on the most valuable displacement
  opportunity or the most critical vendor gap. Name specific products and competitors.
  Suggest a concrete action: offer a POC, propose a buyout, position a bundle.
  Do not use bullet points or headers. Output only the comment text, nothing else.
```

- [ ] **Step 3: Verify config loads without errors**

Run: `python3 -c "from src.utils.config_loader import load_regions_config, load_prompt_templates; r = load_regions_config(); t = load_prompt_templates(); print('write_tabs:', r.get('comment_write_tabs')); print('portfolio template len:', len(t.get('portfolio_prompt_template', ''))); print('tech stake template len:', len(t.get('tech_stake_prompt_template', '')))"`

Expected: All three print statements show non-zero values.

- [ ] **Step 4: Commit**

```bash
git add config/regions.yaml config/prompt_templates.yaml
git commit -m "feat: add multi-tab write-back config and portfolio/tech-stake prompt templates"
```

---

### Task 2: Portfolio comment generator

**Files:**
- Create: `src/llm/portfolio_comment.py`
- Create: `tests/test_portfolio_comment.py`

- [ ] **Step 1: Write the test for portfolio metric aggregation**

```python
# tests/test_portfolio_comment.py
"""Tests for portfolio comment generation."""
import pytest
import pandas as pd

from src.llm.portfolio_comment import aggregate_portfolio_metrics


def _sample_scored_df():
    """Create a minimal scored DataFrame for testing."""
    return pd.DataFrame([
        {
            "account_name": "Acme Corp", "region": "APAC", "arr": 50000,
            "nrr_display": "85%", "nrr_tier": "CRITICAL", "attention_tier": "P1",
            "composite_score": 78, "primary_signal": "NRR CRITICAL",
            "renewal_date": "2026-04-15", "competitor_channels": [{"channel": "CDP", "vendor": "Salesforce"}],
            "whitespace_channels": ["Smart Recommender"], "insider_product_count": 2,
        },
        {
            "account_name": "Beta Inc", "region": "APAC", "arr": 30000,
            "nrr_display": "105%", "nrr_tier": "HEALTHY", "attention_tier": "P3",
            "composite_score": 25, "primary_signal": "On track",
            "renewal_date": "2026-09-01", "competitor_channels": [],
            "whitespace_channels": [], "insider_product_count": 5,
        },
        {
            "account_name": "Gamma LLC", "region": "APAC", "arr": 80000,
            "nrr_display": "95%", "nrr_tier": "AT_RISK", "attention_tier": "P2",
            "composite_score": 55, "primary_signal": "NRR AT_RISK",
            "renewal_date": "2026-05-20", "competitor_channels": [{"channel": "Email", "vendor": "Klaviyo"}],
            "whitespace_channels": ["Eureka Search", "Shopping Agent"], "insider_product_count": 3,
        },
    ])


def test_aggregate_portfolio_metrics_counts():
    df = _sample_scored_df()
    metrics = aggregate_portfolio_metrics(df, region="APAC")
    assert metrics["total_accounts"] == 3
    assert metrics["p1_count"] == 1
    assert metrics["p2_count"] == 1
    assert metrics["p3_count"] == 1


def test_aggregate_portfolio_metrics_arr():
    df = _sample_scored_df()
    metrics = aggregate_portfolio_metrics(df, region="APAC")
    assert metrics["total_arr"] == "$160,000"


def test_aggregate_portfolio_metrics_nrr_distribution():
    df = _sample_scored_df()
    metrics = aggregate_portfolio_metrics(df, region="APAC")
    assert metrics["nrr_critical_count"] == 1
    assert metrics["nrr_at_risk_count"] == 1
    assert metrics["nrr_healthy_count"] == 1
    assert metrics["nrr_strong_count"] == 0


def test_aggregate_portfolio_metrics_top_5():
    df = _sample_scored_df()
    metrics = aggregate_portfolio_metrics(df, region="APAC")
    # Top 5 should be sorted by composite_score desc
    assert "Acme Corp" in metrics["top_5_accounts"]
    assert "Gamma LLC" in metrics["top_5_accounts"]


def test_aggregate_portfolio_metrics_opportunities():
    df = _sample_scored_df()
    metrics = aggregate_portfolio_metrics(df, region="APAC")
    assert metrics["competitor_opportunity_count"] == 2  # Acme + Gamma
    assert metrics["whitespace_opportunity_count"] == 2  # Acme + Gamma
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m pytest tests/test_portfolio_comment.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.llm.portfolio_comment'`

- [ ] **Step 3: Implement portfolio_comment.py**

```python
# src/llm/portfolio_comment.py
"""
Portfolio-level CRO comment generation for the Overview tab.

Aggregates scored_df metrics per region and generates a single
CRO-voiced portfolio summary comment.
"""

import logging
from typing import Optional

import pandas as pd

from src.llm.client import call_claude, DEFAULT_MODEL
from src.llm.prompt_builder import build_system_prompt
from src.utils.config_loader import load_prompt_templates, load_cro_persona, load_tone_profile

logger = logging.getLogger(__name__)


def aggregate_portfolio_metrics(scored_df: pd.DataFrame, region: str = "") -> dict:
    """
    Compute portfolio-level metrics from the scored DataFrame.

    Args:
        scored_df: Full scored master DataFrame.
        region: If non-empty, filter to this region only.

    Returns:
        Dict with all template placeholders for portfolio_prompt_template.
    """
    df = scored_df.copy()
    if region and "region" in df.columns:
        df = df[df["region"] == region]

    total = len(df)

    # Tier counts
    tier_counts = df["attention_tier"].value_counts() if "attention_tier" in df.columns else pd.Series()
    p1 = int(tier_counts.get("P1", 0))
    p2 = int(tier_counts.get("P2", 0))
    p3 = int(tier_counts.get("P3", 0))

    # ARR
    arr_total = 0
    if "arr" in df.columns:
        arr_series = pd.to_numeric(
            df["arr"].astype(str).str.replace(r"[$,]", "", regex=True),
            errors="coerce",
        )
        arr_total = arr_series.sum()
    arr_display = f"${arr_total:,.0f}" if arr_total else "N/A"

    # NRR average
    nrr_vals = []
    if "nrr_display" in df.columns:
        for v in df["nrr_display"]:
            try:
                nrr_vals.append(float(str(v).replace("%", "").strip()))
            except (ValueError, TypeError):
                pass
    avg_nrr = f"{sum(nrr_vals) / len(nrr_vals):.1f}%" if nrr_vals else "N/A"

    # NRR distribution
    nrr_dist = df["nrr_tier"].value_counts() if "nrr_tier" in df.columns else pd.Series()

    # Top 5 by composite score
    top5_df = df.nlargest(5, "composite_score") if "composite_score" in df.columns else df.head(5)
    top5_lines = []
    for _, r in top5_df.iterrows():
        name = str(r.get("account_name", "Unknown")).strip()
        arr = r.get("arr", "N/A")
        tier = r.get("attention_tier", "?")
        signal = str(r.get("primary_signal", "")).strip()
        top5_lines.append(f"- {name} | ARR: {arr} | {tier} | {signal}")
    top5_text = "\n  ".join(top5_lines) if top5_lines else "None"

    # Upcoming renewals (next 90 days)
    renewal_lines = []
    if "renewal_date" in df.columns:
        now = pd.Timestamp.now()
        for _, r in df.iterrows():
            try:
                rd = pd.to_datetime(r["renewal_date"], errors="coerce")
                if pd.notna(rd):
                    days = (rd - now).days
                    if 0 <= days <= 90:
                        name = str(r.get("account_name", "")).strip()
                        renewal_lines.append(f"- {name}: {days} days (renews {r['renewal_date']})")
            except Exception:
                pass
    renewal_text = "\n  ".join(renewal_lines) if renewal_lines else "None in next 90 days"

    # Competitor + whitespace opportunity counts
    competitor_count = 0
    whitespace_count = 0
    displacement_count = 0
    for _, r in df.iterrows():
        comp = r.get("competitor_channels", [])
        ws = r.get("whitespace_channels", [])
        if isinstance(comp, str):
            try:
                import ast
                comp = ast.literal_eval(comp)
            except Exception:
                comp = []
        if isinstance(ws, str):
            try:
                import ast
                ws = ast.literal_eval(ws)
            except Exception:
                ws = []
        if comp:
            competitor_count += 1
        if ws:
            whitespace_count += 1
        if comp or ws:
            displacement_count += 1

    return {
        "region": region or "All Regions",
        "total_accounts": total,
        "total_arr": arr_display,
        "avg_nrr": avg_nrr,
        "p1_count": p1,
        "p2_count": p2,
        "p3_count": p3,
        "nrr_critical_count": int(nrr_dist.get("CRITICAL", 0)),
        "nrr_at_risk_count": int(nrr_dist.get("AT_RISK", 0)),
        "nrr_healthy_count": int(nrr_dist.get("HEALTHY", 0)),
        "nrr_strong_count": int(nrr_dist.get("STRONG", 0)),
        "top_5_accounts": top5_text,
        "upcoming_renewals": renewal_text,
        "competitor_opportunity_count": competitor_count,
        "whitespace_opportunity_count": whitespace_count,
        "displacement_count": displacement_count,
    }


def build_portfolio_user_prompt(metrics: dict, templates: dict) -> str:
    """
    Build the user prompt for portfolio comment generation.

    Args:
        metrics: Output of aggregate_portfolio_metrics().
        templates: Loaded prompt_templates.yaml.

    Returns:
        Formatted user prompt string.
    """
    template = templates.get("portfolio_prompt_template")
    if not template:
        raise ValueError("portfolio_prompt_template not found in prompt_templates.yaml")

    sentence_count = templates.get("sentence_count", "2-3")
    return template.format(sentence_count=sentence_count, **metrics)


def generate_portfolio_comment(
    scored_df: pd.DataFrame,
    region: str,
    client,
    system_prompt: str,
    templates: dict,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
) -> str:
    """
    Generate a single CRO-voiced portfolio summary comment for a region.

    Args:
        scored_df: Full scored master DataFrame.
        region: Region to generate for (empty = all regions).
        client: Initialized Anthropic client.
        system_prompt: Pre-built system prompt.
        templates: Loaded prompt_templates.yaml.
        model: Claude model.
        temperature: Generation temperature.

    Returns:
        Generated portfolio comment text.
    """
    metrics = aggregate_portfolio_metrics(scored_df, region)
    user_prompt = build_portfolio_user_prompt(metrics, templates)
    comment = call_claude(
        client=client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=temperature,
    )
    return comment
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m pytest tests/test_portfolio_comment.py -v`

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/llm/portfolio_comment.py tests/test_portfolio_comment.py
git commit -m "feat: add portfolio comment generator with metric aggregation"
```

---

### Task 3: Tech stake comment generator

**Files:**
- Create: `src/llm/tech_stake_comment.py`
- Create: `tests/test_tech_stake_comment.py`

- [ ] **Step 1: Write the test for vendor gap detection**

```python
# tests/test_tech_stake_comment.py
"""Tests for tech stake comment generation."""
import pytest
import pandas as pd

from src.llm.tech_stake_comment import (
    detect_vendor_gaps,
    filter_accounts_with_gaps,
)


def _sample_row():
    return pd.Series({
        "account_name": "Acme Corp",
        "region": "APAC",
        "ae_name": "John Smith",
        "arr": 50000,
        "nrr_display": "85%",
        "insider_product_count": 2,
        "insider_channels": ["CDP", "Email Promotional"],
        "competitor_channels": [
            {"channel": "Smart Recommender", "vendor": "Algolia"},
            {"channel": "Customer Support Chatbot", "vendor": "Zendesk"},
        ],
        "whitespace_channels": ["Eureka Search", "Shopping Agent", "Gamification"],
        "expansion_score": 72,
    })


def test_detect_vendor_gaps_competitors():
    row = _sample_row()
    gaps = detect_vendor_gaps(row)
    assert len(gaps["competitor_gaps"]) == 2
    assert any("Algolia" in g for g in gaps["competitor_gaps"])
    assert any("Zendesk" in g for g in gaps["competitor_gaps"])


def test_detect_vendor_gaps_whitespace():
    row = _sample_row()
    gaps = detect_vendor_gaps(row)
    assert len(gaps["whitespace_gaps"]) == 3
    assert "Eureka Search" in gaps["whitespace_gaps"]


def test_detect_vendor_gaps_has_gaps():
    row = _sample_row()
    gaps = detect_vendor_gaps(row)
    assert gaps["has_gaps"] is True


def test_detect_vendor_gaps_no_gaps():
    row = pd.Series({
        "account_name": "Happy Corp",
        "competitor_channels": [],
        "whitespace_channels": [],
    })
    gaps = detect_vendor_gaps(row)
    assert gaps["has_gaps"] is False


def test_filter_accounts_with_gaps():
    df = pd.DataFrame([
        {
            "account_name": "Acme", "arr": 50000, "attention_tier": "P1",
            "competitor_channels": [{"channel": "CDP", "vendor": "Salesforce"}],
            "whitespace_channels": ["Eureka"],
        },
        {
            "account_name": "Beta", "arr": 10000, "attention_tier": "P3",
            "competitor_channels": [],
            "whitespace_channels": [],
        },
        {
            "account_name": "Gamma", "arr": 80000, "attention_tier": "P2",
            "competitor_channels": [],
            "whitespace_channels": ["Shopping Agent"],
        },
    ])
    filtered = filter_accounts_with_gaps(df, min_arr=5000)
    assert len(filtered) == 2
    # Should be sorted by ARR descending
    assert filtered.iloc[0]["account_name"] == "Gamma"
    assert filtered.iloc[1]["account_name"] == "Acme"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m pytest tests/test_tech_stake_comment.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement tech_stake_comment.py**

```python
# src/llm/tech_stake_comment.py
"""
Tech stake CRO comment generation for the Current Tech Stack Information tab.

Identifies vendor gaps per account and generates displacement-focused
CRO comments.
"""

import ast
import logging
from typing import Optional

import pandas as pd

from src.llm.client import call_claude, DEFAULT_MODEL
from src.llm.prompt_builder import build_system_prompt, extract_channel_context
from src.utils.config_loader import load_prompt_templates

logger = logging.getLogger(__name__)


def _ensure_list(val):
    """Convert string-serialized lists back to Python lists."""
    if isinstance(val, list):
        return val
    if isinstance(val, str) and val.startswith("["):
        try:
            return ast.literal_eval(val)
        except Exception:
            return []
    return []


def detect_vendor_gaps(row: pd.Series) -> dict:
    """
    Analyze a single account row for vendor gaps.

    Returns:
        Dict with:
        - competitor_gaps: list of "Channel: Vendor" strings
        - whitespace_gaps: list of channel name strings
        - has_gaps: bool
        - gap_count: int
    """
    competitor_channels = _ensure_list(row.get("competitor_channels", []))
    whitespace_channels = _ensure_list(row.get("whitespace_channels", []))

    competitor_gaps = []
    for entry in competitor_channels:
        if isinstance(entry, dict):
            competitor_gaps.append(f"{entry.get('channel', '?')}: {entry.get('vendor', '?')}")
        elif isinstance(entry, str):
            competitor_gaps.append(entry)

    whitespace_gaps = list(whitespace_channels)

    return {
        "competitor_gaps": competitor_gaps,
        "whitespace_gaps": whitespace_gaps,
        "has_gaps": bool(competitor_gaps or whitespace_gaps),
        "gap_count": len(competitor_gaps) + len(whitespace_gaps),
    }


def filter_accounts_with_gaps(
    scored_df: pd.DataFrame,
    min_arr: float = 5000,
    region: str = "",
) -> pd.DataFrame:
    """
    Filter scored_df to accounts that have vendor gaps, sorted by ARR descending.

    Args:
        scored_df: Full scored DataFrame.
        min_arr: Minimum ARR to include (default $5K per CRO priority).
        region: If non-empty, filter to this region.

    Returns:
        Filtered DataFrame with only accounts that have gaps.
    """
    df = scored_df.copy()
    if region and "region" in df.columns:
        df = df[df["region"] == region]

    # Filter to accounts with gaps
    has_gap = []
    for _, row in df.iterrows():
        gaps = detect_vendor_gaps(row)
        has_gap.append(gaps["has_gaps"])
    df = df[has_gap].copy()

    # Filter by ARR
    if "arr" in df.columns:
        arr_numeric = pd.to_numeric(
            df["arr"].astype(str).str.replace(r"[$,]", "", regex=True),
            errors="coerce",
        ).fillna(0)
        df = df[arr_numeric >= min_arr].copy()
        # Sort by ARR descending
        df["_arr_sort"] = arr_numeric[df.index]
        df = df.sort_values("_arr_sort", ascending=False).drop(columns=["_arr_sort"])

    return df.reset_index(drop=True)


def build_tech_stake_user_prompt(
    row: pd.Series,
    scoring: dict,
    templates: dict,
) -> str:
    """
    Build the user prompt for a tech stake comment.

    Args:
        row: Account row from scored DataFrame.
        scoring: Scoring results dict for this row.
        templates: Loaded prompt_templates.yaml.

    Returns:
        Formatted user prompt string.
    """
    template = templates.get("tech_stake_prompt_template")
    if not template:
        raise ValueError("tech_stake_prompt_template not found in prompt_templates.yaml")

    gaps = detect_vendor_gaps(row)
    channel_ctx = extract_channel_context(row, scoring)

    insider_channels = channel_ctx.get("insider_channels", [])
    insider_display = ", ".join(insider_channels) if insider_channels else "None detected"

    vendor_gaps_text = "\n  ".join(f"- {g}" for g in gaps["competitor_gaps"]) if gaps["competitor_gaps"] else "None identified"
    whitespace_text = "\n  ".join(f"- {g}" for g in gaps["whitespace_gaps"]) if gaps["whitespace_gaps"] else "None identified"

    coexisting = str(row.get("coexisting_competitors", row.get("do they have co existing competitor", ""))).strip()
    coexisting = coexisting if coexisting and coexisting.lower() not in ("nan", "") else "None noted"

    arr_raw = row.get("arr")
    try:
        arr_num = float(str(arr_raw).replace("$", "").replace(",", "").strip())
        arr_display = f"${arr_num:,.0f}"
    except (ValueError, TypeError):
        arr_display = str(arr_raw) if arr_raw else "N/A"

    sentence_count = templates.get("sentence_count", "2-3")

    return template.format(
        sentence_count=sentence_count,
        account_name=str(row.get("account_name", "Unknown")).strip(),
        region=str(row.get("region", "Unknown")).strip(),
        ae_name=str(row.get("ae_name", "N/A")).strip() or "N/A",
        arr_display=arr_display,
        nrr_display=scoring.get("nrr_display", "N/A"),
        insider_product_count=channel_ctx.get("insider_count", 0),
        total_channels=channel_ctx.get("total_channels", 16),
        insider_channels_display=insider_display,
        vendor_gaps=vendor_gaps_text,
        whitespace_gaps=whitespace_text,
        coexisting_competitors=coexisting,
    )


def generate_tech_stake_comment(
    row: pd.Series,
    scoring: dict,
    client,
    system_prompt: str,
    templates: dict,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
) -> str:
    """
    Generate a CRO-voiced tech stake comment for a single account.

    Args:
        row: Account row from scored DataFrame.
        scoring: Scoring results dict.
        client: Initialized Anthropic client.
        system_prompt: Pre-built system prompt.
        templates: Loaded prompt_templates.yaml.
        model: Claude model.
        temperature: Generation temperature.

    Returns:
        Generated tech stake comment text.
    """
    user_prompt = build_tech_stake_user_prompt(row, scoring, templates)
    comment = call_claude(
        client=client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=temperature,
    )
    return comment
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m pytest tests/test_tech_stake_comment.py -v`

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/llm/tech_stake_comment.py tests/test_tech_stake_comment.py
git commit -m "feat: add tech stake comment generator with vendor gap detection"
```

---

### Task 4: Overview tab write-back

**Files:**
- Modify: `src/google/sheets_client.py` (add new function after line 380)

- [ ] **Step 1: Write the test**

```python
# tests/test_overview_writeback.py
"""Tests for overview tab write-back cell targeting."""
from src.google.sheets_client import _col_index_to_letter


def test_col_index_to_letter_single():
    assert _col_index_to_letter(1) == "A"
    assert _col_index_to_letter(26) == "Z"


def test_col_index_to_letter_double():
    assert _col_index_to_letter(27) == "AA"
    assert _col_index_to_letter(28) == "AB"
```

- [ ] **Step 2: Run test to verify it passes (existing function)**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m pytest tests/test_overview_writeback.py -v`

Expected: PASS (function already exists).

- [ ] **Step 3: Add write_portfolio_comment() to sheets_client.py**

Append this function after the `_col_index_to_letter` function (after line 412):

```python
def write_portfolio_comment(
    sheets_service,
    spreadsheet_id: str,
    sheet_name: str,
    comment_text: str,
    target_cell: str = "",
) -> tuple:
    """
    Write a single portfolio-level CRO comment to the Overview tab.

    Unlike write_comments_to_summary() which matches per-account rows,
    this writes one comment to a designated cell. If target_cell is empty,
    it finds or creates a 'CRO Portfolio Comment' row after the last data row.

    Args:
        sheets_service: Authenticated Sheets API service.
        spreadsheet_id: Target spreadsheet ID.
        sheet_name: Overview tab name.
        comment_text: The portfolio CRO comment.
        target_cell: Optional explicit A1 cell reference (e.g., "A50").
                     If empty, auto-detects placement.

    Returns:
        Tuple of (success: bool, debug_info: dict).
    """
    debug_info = {
        "sheet_name": sheet_name,
        "target_cell": None,
        "error": None,
    }

    if not comment_text:
        debug_info["error"] = "Empty comment text"
        return False, debug_info

    try:
        if target_cell:
            # Write to explicit cell
            cell_ref = f"'{sheet_name}'!{target_cell}"
        else:
            # Read the sheet to find last data row
            range_notation = f"'{sheet_name}'"
            result = (
                sheets_service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=range_notation)
                .execute()
            )
            rows = result.get("values", [])
            last_row = len(rows) + 1  # 1-indexed, next empty row

            # Check if "CRO Portfolio Comment" label already exists
            label_row = None
            for i, row in enumerate(rows):
                if row and "cro portfolio comment" in str(row[0]).lower():
                    label_row = i + 1  # 1-indexed
                    break

            if label_row:
                # Write comment next to existing label (column B)
                cell_ref = f"'{sheet_name}'!B{label_row}"
            else:
                # Create label + comment in the next empty row (skip one row for spacing)
                label_ref = f"'{sheet_name}'!A{last_row + 1}"
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=label_ref,
                    valueInputOption="RAW",
                    body={"values": [["CRO Portfolio Comment"]]},
                ).execute()
                cell_ref = f"'{sheet_name}'!B{last_row + 1}"

        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=cell_ref,
            valueInputOption="RAW",
            body={"values": [[comment_text]]},
        ).execute()

        debug_info["target_cell"] = cell_ref
        return True, debug_info

    except Exception as exc:
        logger.error("Failed to write portfolio comment: %s", exc)
        debug_info["error"] = str(exc)
        return False, debug_info
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -m py_compile src/google/sheets_client.py`

Expected: No output (success).

- [ ] **Step 5: Commit**

```bash
git add src/google/sheets_client.py tests/test_overview_writeback.py
git commit -m "feat: add write_portfolio_comment() for Overview tab write-back"
```

---

## Chunk 2: Frontend — Session State and Three-Step Review UI

### Task 5: Session state for multi-step review

**Files:**
- Modify: `src/session/state.py`

- [ ] **Step 1: Add review_step and comment_type fields**

In `src/session/state.py`, add `comment_type` to `AccountDecision` (after line 22):

```python
    comment_type: str = "account"       # "portfolio" | "account" | "tech_stake"
```

Add `review_step` to `SessionState` (after line 43, the `tiers_reviewed` line):

```python
    review_step: int = 1                # 1=Portfolio, 2=Account Reviews, 3=Tech Stake
    portfolio_decisions: dict = field(default_factory=dict)  # {region_key: AccountDecision}
    tech_stake_order: list[str] = field(default_factory=list)  # Ordered account_keys for tech stake
    tech_stake_decisions: dict = field(default_factory=dict)  # {account_key: AccountDecision}
```

- [ ] **Step 2: Add helper methods for step navigation**

Add these methods to `SessionState` after the `progress_pct()` method (after line 70):

```python
    def advance_step(self) -> None:
        """Move to the next review step (max 3)."""
        if self.review_step < 3:
            self.review_step += 1

    def step_label(self) -> str:
        """Human-readable label for the current step."""
        return {1: "Portfolio Summary", 2: "Account Reviews", 3: "Tech Stack Reviews"}.get(
            self.review_step, "Unknown"
        )

    def portfolio_approved_count(self) -> int:
        return sum(1 for d in self.portfolio_decisions.values() if d.status == "approved")

    def tech_stake_approved_count(self) -> int:
        return sum(1 for d in self.tech_stake_decisions.values() if d.status == "approved")

    def all_approved_decisions(self) -> dict:
        """Return all approved decisions across all three steps."""
        merged = {}
        for k, d in self.portfolio_decisions.items():
            if d.status == "approved":
                merged[k] = d
        for k, d in self.decisions.items():
            if d.status == "approved":
                merged[k] = d
        for k, d in self.tech_stake_decisions.items():
            if d.status == "approved":
                merged[k] = d
        return merged
```

- [ ] **Step 3: Update serialization to handle new fields**

In the `to_dict()` method, add serialization for the new dicts (modify around line 74-77):

```python
    def to_dict(self) -> dict:
        d = asdict(self)
        d["decisions"] = {k: v.to_dict() for k, v in self.decisions.items()}
        d["portfolio_decisions"] = {k: v.to_dict() for k, v in self.portfolio_decisions.items()}
        d["tech_stake_decisions"] = {k: v.to_dict() for k, v in self.tech_stake_decisions.items()}
        return d
```

In the `from_dict()` method, add deserialization (modify around line 80-86):

```python
    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        decisions_raw = d.pop("decisions", {})
        portfolio_raw = d.pop("portfolio_decisions", {})
        tech_stake_raw = d.pop("tech_stake_decisions", {})
        session = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        session.decisions = {
            k: AccountDecision.from_dict(v) for k, v in decisions_raw.items()
        }
        session.portfolio_decisions = {
            k: AccountDecision.from_dict(v) for k, v in portfolio_raw.items()
        }
        session.tech_stake_decisions = {
            k: AccountDecision.from_dict(v) for k, v in tech_stake_raw.items()
        }
        return session
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -m py_compile src/session/state.py`

Expected: No output (success).

- [ ] **Step 5: Commit**

```bash
git add src/session/state.py
git commit -m "feat: add multi-step review state (portfolio, account, tech_stake)"
```

---

### Task 6: Three-step review UI

**Files:**
- Modify: `pages/review.py` (major update)

This is the largest task. It modifies `render_review_page()` to add a step indicator and routes to the correct step UI.

- [ ] **Step 1: Add the step indicator and routing to render_review_page()**

Replace the current `render_review_page()` function (lines 32-55) with:

```python
def render_review_page():
    """Main entry point for the Review tab — three-step CRO review flow."""
    filters = render_progress_sidebar()

    scored_df: pd.DataFrame = st.session_state.get("scored_df", pd.DataFrame())
    if scored_df.empty:
        st.warning("No data loaded. Go to the main page and wait for data to load.")
        return

    # ── Session initialization
    if "session" not in st.session_state:
        _initialize_session(scored_df, filters)
        return

    session: SessionState = st.session_state["session"]

    # ── Step indicator
    _render_step_indicator(session.review_step)

    # ── Route to current step
    if session.review_step == 1:
        _render_portfolio_step(scored_df, session)
    elif session.review_step == 2:
        # Two-panel layout (existing)
        left_col, right_col = st.columns([1, 2])
        with left_col:
            _render_left_panel(scored_df, session)
        with right_col:
            _render_right_panel(scored_df, session)
    elif session.review_step == 3:
        _render_tech_stake_step(scored_df, session)
```

- [ ] **Step 2: Add the step indicator renderer**

Add this new function (before `_handle_approve`):

```python
def _render_step_indicator(current_step: int) -> None:
    """Render a horizontal step progress indicator."""
    steps = [
        (1, "Portfolio Summary", "Overview tab"),
        (2, "Account Reviews", "Maps tab"),
        (3, "Tech Stack Reviews", "Tech Stack tab"),
    ]
    cols = st.columns(len(steps))
    for col, (num, label, target) in zip(cols, steps):
        with col:
            if num < current_step:
                # Completed
                st.markdown(
                    f"<div style='text-align:center;padding:8px;background:#1a3a2a;"
                    f"border-radius:6px;border:1px solid #22c55e'>"
                    f"<span style='color:#22c55e;font-weight:bold'>✓ Step {num}</span><br/>"
                    f"<span style='color:#86efac;font-size:0.8rem'>{label}</span></div>",
                    unsafe_allow_html=True,
                )
            elif num == current_step:
                # Active
                st.markdown(
                    f"<div style='text-align:center;padding:8px;background:#1e3a5f;"
                    f"border-radius:6px;border:2px solid #3b82f6'>"
                    f"<span style='color:#3b82f6;font-weight:bold'>Step {num}</span><br/>"
                    f"<span style='color:#93c5fd;font-size:0.8rem'>{label}</span><br/>"
                    f"<span style='color:#64748b;font-size:0.7rem'>→ {target}</span></div>",
                    unsafe_allow_html=True,
                )
            else:
                # Upcoming
                st.markdown(
                    f"<div style='text-align:center;padding:8px;background:#1e293b;"
                    f"border-radius:6px;border:1px solid #334155'>"
                    f"<span style='color:#64748b;font-weight:bold'>Step {num}</span><br/>"
                    f"<span style='color:#475569;font-size:0.8rem'>{label}</span></div>",
                    unsafe_allow_html=True,
                )
    st.markdown("---")
```

- [ ] **Step 3: Add the portfolio summary step UI**

Add this function for Step 1:

```python
def _render_portfolio_step(scored_df: pd.DataFrame, session: SessionState) -> None:
    """Render Step 1: Portfolio Summary — one CRO comment per region for Overview tab."""
    from src.llm.portfolio_comment import (
        aggregate_portfolio_metrics,
        generate_portfolio_comment,
    )

    st.subheader("Step 1: Portfolio Summary")
    st.caption("Review the regional portfolio and approve a CRO comment for the Overview tab.")

    # Get available regions
    regions = sorted(scored_df["region"].unique().tolist()) if "region" in scored_df.columns else ["All"]

    # Region selector
    selected_region = st.selectbox("Select Region", regions, key="portfolio_region")

    # Compute portfolio metrics
    metrics = aggregate_portfolio_metrics(scored_df, region=selected_region)

    # Display key metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Accounts", metrics["total_accounts"])
    m2.metric("Total ARR", metrics["total_arr"])
    m3.metric("Avg NRR", metrics["avg_nrr"])
    m4.metric("P1 Critical", metrics["p1_count"])

    # NRR distribution
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**NRR Risk Distribution**")
        st.markdown(
            f"- CRITICAL: {metrics['nrr_critical_count']}  \n"
            f"- AT_RISK: {metrics['nrr_at_risk_count']}  \n"
            f"- HEALTHY: {metrics['nrr_healthy_count']}  \n"
            f"- STRONG: {metrics['nrr_strong_count']}"
        )
    with col2:
        st.markdown("**Expansion Opportunities**")
        st.markdown(
            f"- Competitor displacement: {metrics['competitor_opportunity_count']} accounts  \n"
            f"- Whitespace channels: {metrics['whitespace_opportunity_count']} accounts  \n"
            f"- Total opportunities: {metrics['displacement_count']} accounts"
        )

    st.markdown("---")

    # Portfolio comment generation / display
    region_key = f"PORTFOLIO::{selected_region}"
    existing_decision = session.portfolio_decisions.get(region_key)

    if existing_decision and existing_decision.status == "approved":
        st.success(f"✅ Portfolio comment for {selected_region} approved.")
        st.text_area("Approved Comment", value=existing_decision.final_comment, disabled=True, height=120)
    else:
        # Generate or retrieve comment
        comment_cache_key = f"portfolio_comment_{selected_region}"
        if comment_cache_key not in st.session_state:
            model = st.session_state.get("selected_model", "claude-sonnet-4-6")
            with st.spinner(f"Generating portfolio comment for {selected_region}..."):
                try:
                    client = get_anthropic_client()
                    templates = load_prompt_templates()
                    system_prompt = st.session_state.get("system_prompt") or build_shared_system_prompt(templates=templates)
                    st.session_state["system_prompt"] = system_prompt

                    comment = generate_portfolio_comment(
                        scored_df=scored_df,
                        region=selected_region,
                        client=client,
                        system_prompt=system_prompt,
                        templates=templates,
                        model=model,
                    )
                    st.session_state[comment_cache_key] = comment
                except Exception as exc:
                    st.error(f"Portfolio comment generation failed: {exc}")
                    st.session_state[comment_cache_key] = f"[Generation failed: {exc}]"

        portfolio_comment = st.session_state.get(comment_cache_key, "")

        edited_comment = st.text_area(
            "CRO Portfolio Comment (edit before approving):",
            value=portfolio_comment,
            height=140,
            key=f"portfolio_area_{selected_region}",
        )

        # Action buttons
        act1, act2, act3 = st.columns([2, 1, 2])
        with act1:
            if st.button("✅ Approve Portfolio Comment", type="primary", key="approve_portfolio"):
                from src.session.persistence import save_session
                decision = AccountDecision(
                    account_key=region_key,
                    status="approved",
                    final_comment=edited_comment.strip(),
                    original_comment=portfolio_comment,
                    edited=edited_comment.strip() != portfolio_comment.strip(),
                    comment_type="portfolio",
                )
                session.portfolio_decisions[region_key] = decision
                session.last_saved_at = __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat()
                save_session(session, DEFAULT_SESSION_DIR)
                st.session_state["session"] = session
                st.toast(f"✅ Portfolio comment for {selected_region} approved!")
                st.rerun()

        with act2:
            if st.button("🔄 Regenerate", key="regen_portfolio"):
                if comment_cache_key in st.session_state:
                    del st.session_state[comment_cache_key]
                st.rerun()

    # Check if all regions have portfolio comments
    all_regions_done = all(
        f"PORTFOLIO::{r}" in session.portfolio_decisions
        and session.portfolio_decisions[f"PORTFOLIO::{r}"].status == "approved"
        for r in regions
    )

    st.markdown("---")

    # Navigation
    nav1, nav2 = st.columns([3, 1])
    with nav2:
        if st.button("Next Step → Account Reviews", key="to_step_2",
                      type="primary" if all_regions_done else "secondary"):
            session.review_step = 2
            session.last_saved_at = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat()
            save_session(session, DEFAULT_SESSION_DIR)
            st.session_state["session"] = session
            st.rerun()

    with nav1:
        if not all_regions_done:
            pending = [r for r in regions if f"PORTFOLIO::{r}" not in session.portfolio_decisions
                       or session.portfolio_decisions[f"PORTFOLIO::{r}"].status != "approved"]
            st.caption(f"Pending regions: {', '.join(pending)}")
```

- [ ] **Step 4: Add the tech stake review step UI**

Add this function for Step 3:

```python
def _render_tech_stake_step(scored_df: pd.DataFrame, session: SessionState) -> None:
    """Render Step 3: Tech Stack Reviews — per-account vendor gap comments."""
    from src.llm.tech_stake_comment import (
        filter_accounts_with_gaps,
        generate_tech_stake_comment,
        detect_vendor_gaps,
    )
    from src.llm.comment_generator import _extract_scoring_from_row

    st.subheader("Step 3: Tech Stack Reviews")
    st.caption("Review accounts with vendor gaps and approve CRO comments for the Current Tech Stack Information tab.")

    # Initialize tech stake order if needed
    if not session.tech_stake_order:
        gap_df = filter_accounts_with_gaps(scored_df, min_arr=5000)
        from src.ingestion.joiner import get_account_key
        session.tech_stake_order = [get_account_key(row) for _, row in gap_df.iterrows()]
        st.session_state["session"] = session

    if not session.tech_stake_order:
        st.info("No accounts with vendor gaps found (ARR > $5K). Tech stake review complete.")
        _render_save_all_button(session, scored_df)
        return

    # Two-panel layout
    left_col, right_col = st.columns([1, 2])

    with left_col:
        st.markdown(f"**Accounts with Gaps** ({len(session.tech_stake_order)})")
        done = session.tech_stake_approved_count()
        st.progress(done / len(session.tech_stake_order) if session.tech_stake_order else 0)
        st.caption(f"{done} / {len(session.tech_stake_order)} reviewed")

        # Account list
        if "ts_selected_key" not in st.session_state and session.tech_stake_order:
            st.session_state["ts_selected_key"] = session.tech_stake_order[0]

        with st.container(height=400):
            for idx, key in enumerate(session.tech_stake_order):
                decision = session.tech_stake_decisions.get(key)
                status = decision.status if decision else "pending"
                status_icon = {"approved": "✅", "skipped": "⏭️"}.get(status, "⬜")
                selected = key == st.session_state.get("ts_selected_key")
                name = key.split("::")[1] if "::" in key else key

                if st.button(
                    f"{status_icon} {name}",
                    key=f"ts_row_{idx}",
                    use_container_width=True,
                ):
                    st.session_state["ts_selected_key"] = key
                    st.rerun()

    with right_col:
        selected_key = st.session_state.get("ts_selected_key")
        if not selected_key:
            st.info("Select an account from the list.")
            return

        # Find account row
        from src.ingestion.joiner import get_account_key
        account_row = None
        for _, row in scored_df.iterrows():
            if get_account_key(row) == selected_key:
                account_row = row
                break

        if account_row is None:
            st.error(f"Account '{selected_key}' not found.")
            return

        scoring = _extract_scoring_from_row(account_row)
        gaps = detect_vendor_gaps(account_row)

        # Account header
        account_name = str(account_row.get("account_name", "Unknown")).strip()
        region = str(account_row.get("region", "")).strip()
        st.markdown(f"### {account_name}")
        st.caption(f"Region: {region} | AE: {account_row.get('ae_name', 'N/A')}")

        # Gap summary
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Competitor-held Channels:**")
            for g in gaps["competitor_gaps"]:
                st.markdown(f"- 🔴 {g}")
            if not gaps["competitor_gaps"]:
                st.markdown("*None*")
        with col2:
            st.markdown("**Whitespace (uncaptured):**")
            for g in gaps["whitespace_gaps"]:
                st.markdown(f"- ⚪ {g}")
            if not gaps["whitespace_gaps"]:
                st.markdown("*None*")

        st.markdown("---")

        # Comment generation
        existing = session.tech_stake_decisions.get(selected_key)
        if existing and existing.status == "approved":
            st.success("✅ Comment approved.")
            st.text_area("Approved", value=existing.final_comment, disabled=True, height=100)
        else:
            ts_comment_key = f"ts_comment_{selected_key}"
            if ts_comment_key not in st.session_state:
                model = st.session_state.get("selected_model", "claude-sonnet-4-6")
                with st.spinner("Generating tech stake comment..."):
                    try:
                        client = get_anthropic_client()
                        templates = load_prompt_templates()
                        system_prompt = st.session_state.get("system_prompt") or build_shared_system_prompt(templates=templates)
                        st.session_state["system_prompt"] = system_prompt

                        comment = generate_tech_stake_comment(
                            row=account_row,
                            scoring=scoring,
                            client=client,
                            system_prompt=system_prompt,
                            templates=templates,
                            model=model,
                        )
                        st.session_state[ts_comment_key] = comment
                    except Exception as exc:
                        st.error(f"Generation failed: {exc}")
                        st.session_state[ts_comment_key] = f"[Failed: {exc}]"

            ts_comment = st.session_state.get(ts_comment_key, "")
            edited = st.text_area(
                "CRO Tech Stake Comment:",
                value=ts_comment,
                height=120,
                key=f"ts_area_{selected_key}",
            )

            # Actions
            a1, a2, a3 = st.columns([2, 1, 1])
            with a1:
                if st.button("✅ Approve & Next", key=f"ts_approve_{selected_key}", type="primary"):
                    from src.session.persistence import save_session
                    decision = AccountDecision(
                        account_key=selected_key,
                        status="approved",
                        final_comment=edited.strip(),
                        original_comment=ts_comment,
                        edited=edited.strip() != ts_comment.strip(),
                        comment_type="tech_stake",
                        spreadsheet_id=str(account_row.get("spreadsheet_id", "")) or None,
                    )
                    session.tech_stake_decisions[selected_key] = decision
                    save_session(session, DEFAULT_SESSION_DIR)
                    st.session_state["session"] = session
                    # Move to next pending
                    for k in session.tech_stake_order:
                        if k not in session.tech_stake_decisions:
                            st.session_state["ts_selected_key"] = k
                            break
                    st.rerun()

            with a2:
                if st.button("⏭️ Skip", key=f"ts_skip_{selected_key}"):
                    from src.session.persistence import save_session
                    decision = AccountDecision(
                        account_key=selected_key,
                        status="skipped",
                        comment_type="tech_stake",
                    )
                    session.tech_stake_decisions[selected_key] = decision
                    save_session(session, DEFAULT_SESSION_DIR)
                    st.session_state["session"] = session
                    for k in session.tech_stake_order:
                        if k not in session.tech_stake_decisions:
                            st.session_state["ts_selected_key"] = k
                            break
                    st.rerun()

            with a3:
                if st.button("🔄 Regen", key=f"ts_regen_{selected_key}"):
                    if ts_comment_key in st.session_state:
                        del st.session_state[ts_comment_key]
                    st.rerun()

    # Save all button
    st.markdown("---")
    _render_save_all_button(session, scored_df)

    # Back button
    if st.button("← Back to Account Reviews", key="back_to_step2"):
        session.review_step = 2
        st.session_state["session"] = session
        st.rerun()
```

- [ ] **Step 5: Add the multi-tab save function**

Add this function to handle saving across all three tabs:

```python
def _render_save_all_button(session: SessionState, scored_df: pd.DataFrame) -> None:
    """Render a save button that writes all approved comments to their respective tabs."""
    all_approved = session.all_approved_decisions()
    if not all_approved:
        st.info("No approved comments to save yet.")
        return

    # Count by type
    portfolio_count = sum(1 for d in all_approved.values() if d.comment_type == "portfolio")
    account_count = sum(1 for d in all_approved.values() if d.comment_type == "account")
    tech_count = sum(1 for d in all_approved.values() if d.comment_type == "tech_stake")

    label = f"💾 Save All ({portfolio_count} portfolio + {account_count} account + {tech_count} tech stake)"
    if st.button(label, key="save_all_tabs", type="primary"):
        _save_all_tabs(session, scored_df)


def _save_all_tabs(session: SessionState, scored_df: pd.DataFrame):
    """Write approved comments to their respective tabs (Overview, Maps, Tech Stack)."""
    from src.google.auth import get_google_credentials
    from src.google.sheets_client import (
        build_sheets_service, detect_sheet_names,
        write_comments_to_summary, write_portfolio_comment,
    )
    from src.utils.config_loader import load_regions_config
    from collections import defaultdict

    try:
        creds = get_google_credentials()
        sheets_svc = build_sheets_service(creds)
        regions_config = load_regions_config()
        write_tabs = regions_config.get("comment_write_tabs", {})
        portfolio_tab = write_tabs.get("portfolio", "Overview")
        accounts_tab = write_tabs.get("accounts",
                                       regions_config.get("comment_write_tab", "Maps"))
        tech_stake_tab = write_tabs.get("tech_stake", "Current Tech Stake Information")

        total_written = 0
        all_debug = []
        all_approved = session.all_approved_decisions()

        # ── 1. Portfolio comments → Overview tab
        portfolio_decisions = {k: d for k, d in all_approved.items() if d.comment_type == "portfolio"}
        for key, decision in portfolio_decisions.items():
            if not decision.final_comment or not decision.spreadsheet_id:
                # Portfolio comments may not have spreadsheet_id; find from scored_df
                region = key.replace("PORTFOLIO::", "")
                region_rows = scored_df[scored_df["region"] == region] if "region" in scored_df.columns else scored_df
                if not region_rows.empty:
                    sid = str(region_rows.iloc[0].get("spreadsheet_id", ""))
                    if sid:
                        tab_names = detect_sheet_names(sheets_svc, sid)
                        target = next((t for t in tab_names if "overview" in t.lower()), portfolio_tab)
                        success, debug = write_portfolio_comment(
                            sheets_svc, sid, target, decision.final_comment
                        )
                        all_debug.append({"type": "portfolio", "region": region, "debug": debug})
                        if success:
                            total_written += 1

        # ── 2. Account comments → Maps tab
        account_decisions = {k: d for k, d in all_approved.items() if d.comment_type == "account"}
        by_sheet_accounts = defaultdict(dict)
        for key, decision in account_decisions.items():
            if decision.final_comment and decision.spreadsheet_id:
                parts = key.split("::")
                account_name = parts[1] if len(parts) >= 2 else key
                by_sheet_accounts[decision.spreadsheet_id][account_name] = decision.final_comment

        for sid, account_map in by_sheet_accounts.items():
            tab_names = detect_sheet_names(sheets_svc, sid)
            target = accounts_tab if accounts_tab in tab_names else next(
                (t for t in tab_names if "map" in t.lower()), tab_names[0] if tab_names else None
            )
            if target:
                written, debug = write_comments_to_summary(sheets_svc, sid, target, account_map)
                all_debug.append({"type": "accounts", "tab": target, "sheet": sid, "debug": debug})
                total_written += written

        # ── 3. Tech stake comments → Tech Stack tab
        tech_decisions = {k: d for k, d in all_approved.items() if d.comment_type == "tech_stake"}
        by_sheet_tech = defaultdict(dict)
        for key, decision in tech_decisions.items():
            if decision.final_comment and decision.spreadsheet_id:
                parts = key.split("::")
                account_name = parts[1] if len(parts) >= 2 else key
                by_sheet_tech[decision.spreadsheet_id][account_name] = decision.final_comment

        for sid, account_map in by_sheet_tech.items():
            tab_names = detect_sheet_names(sheets_svc, sid)
            target = tech_stake_tab if tech_stake_tab in tab_names else next(
                (t for t in tab_names if "tech" in t.lower() and "stake" in t.lower()),
                next((t for t in tab_names if "tech" in t.lower()), None)
            )
            if target:
                written, debug = write_comments_to_summary(sheets_svc, sid, target, account_map)
                all_debug.append({"type": "tech_stake", "tab": target, "sheet": sid, "debug": debug})
                total_written += written

        # Results
        if total_written > 0:
            st.success(f"💾 Written {total_written} comment(s) across all tabs!")
        else:
            st.error("⚠️ 0 comments written — check diagnostics below.")

        with st.expander("🔍 Multi-tab write-back diagnostics", expanded=(total_written == 0)):
            for entry in all_debug:
                st.json(entry)

    except Exception as exc:
        st.error(f"Multi-tab save failed: {exc}")
```

- [ ] **Step 6: Update _initialize_session to set review_step=1**

In `_initialize_session()`, after `st.session_state["generated_comments"] = {}` (around line 259), add:

```python
    # Initialize tech stake order for Step 3
    from src.llm.tech_stake_comment import filter_accounts_with_gaps
    gap_df = filter_accounts_with_gaps(scored_df, min_arr=5000)
    session.tech_stake_order = [get_account_key(row) for _, row in gap_df.iterrows()]
```

- [ ] **Step 7: Update _save_to_master to use comment_type="account"**

In `_handle_approve()` (line 60), ensure decisions have `comment_type`:

After the `record_decision()` call, the decision already defaults to `comment_type="account"` from the dataclass default. No code change needed here, but verify the default is applied.

- [ ] **Step 8: Add "Next Step" button to Step 2 completion state**

In `_render_right_panel()`, update the completion state block (around lines 568-575). Replace:

```python
    if not pending_in_filter and selected_key in session.decisions:
        st.success(
            "✅ All filtered accounts reviewed. "
            "Change filters or return to the dashboard."
        )
        if st.button("💾 Save to Master Sheets"):
            _save_to_master(session, scored_df)
        return
```

With:

```python
    if not pending_in_filter and selected_key in session.decisions:
        st.success("✅ All account reviews complete!")
        col_save, col_next = st.columns(2)
        with col_save:
            if st.button("💾 Save Account Comments to Maps"):
                _save_to_master(session, scored_df)
        with col_next:
            if st.button("Next Step → Tech Stack Reviews", type="primary"):
                from src.session.persistence import save_session
                session.review_step = 3
                save_session(session, DEFAULT_SESSION_DIR)
                st.session_state["session"] = session
                st.rerun()
        return
```

- [ ] **Step 9: Add ARR-based sorting enhancement to _initialize_session()**

In `_initialize_session()`, after deduplication (around line 248), sort the review_order so ARR > $5K accounts come first:

```python
    # Sort review_order: ARR > $5K first, then by composite_score descending
    key_to_row = {get_account_key(row): row for _, row in df.iterrows()}

    def _sort_key(account_key):
        row = key_to_row.get(account_key)
        if row is None:
            return (1, 0)  # Unknown accounts last
        try:
            arr = float(str(row.get("arr", 0)).replace("$", "").replace(",", "").strip())
        except (ValueError, TypeError):
            arr = 0
        is_high_arr = 0 if arr >= 5000 else 1  # 0 = high ARR first
        composite = float(row.get("composite_score", 0) or 0)
        return (is_high_arr, -composite)

    review_order.sort(key=_sort_key)
```

- [ ] **Step 10: Verify the full file compiles**

Run: `python3 -m py_compile pages/review.py`

Expected: No output (success).

- [ ] **Step 11: Commit**

```bash
git add pages/review.py
git commit -m "feat: three-step CRO review UI (Portfolio → Accounts → Tech Stack)"
```

---

### Task 7: Integration and smoke test

**Files:**
- Modify: `pages/review.py` (add missing imports)

- [ ] **Step 1: Ensure all new imports are present at top of review.py**

Add these imports to the top of `pages/review.py` (after the existing imports):

```python
from src.llm.portfolio_comment import generate_portfolio_comment
from src.llm.tech_stake_comment import generate_tech_stake_comment, detect_vendor_gaps
```

- [ ] **Step 2: Run full syntax check on all modified files**

```bash
cd "/Users/elifbikmaz/Desktop/project dolly"
python3 -m py_compile config/regions.yaml 2>/dev/null; echo "---"
python3 -m py_compile src/session/state.py
python3 -m py_compile src/google/sheets_client.py
python3 -m py_compile src/llm/portfolio_comment.py
python3 -m py_compile src/llm/tech_stake_comment.py
python3 -m py_compile pages/review.py
```

Expected: No errors on any `.py` file.

- [ ] **Step 3: Run all tests**

```bash
cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m pytest tests/ -v
```

Expected: All tests pass (test_portfolio_comment, test_tech_stake_comment, test_overview_writeback, test_risk_summary).

- [ ] **Step 4: Smoke test the app**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m streamlit run app.py --server.port 8504`

Verify:
1. App loads without errors
2. Account Review tab shows the 3-step indicator
3. Step 1 (Portfolio Summary) renders with region selector and metrics
4. Step 2 (Account Reviews) works as before with ARR sorting
5. Step 3 (Tech Stack Reviews) shows accounts with vendor gaps
6. "Save All" button is visible in Step 3

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete multi-tab CRO review flow — Portfolio → Accounts → Tech Stack"
```
