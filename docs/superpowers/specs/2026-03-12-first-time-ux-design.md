# First-Time User Experience: Simplified Review Flow

**Date:** 2026-03-12
**Status:** Approved
**Scope:** `app.py`, `pages/review.py`, `ui/components/review_card.py`, `ui/components/risk_summary.py` (new)

---

## Problem

First-time users — primarily CROs and sales leaders — land on the app and see a wall of raw scores, tier labels, and technical badges (NRR 73/100, SINGLE, AT_RISK, expansion HIGH). They don't understand what these mean or whether the system is working correctly. Two specific issues:

1. **Review card overload** — raw scores and tier labels don't mean anything to a CRO without context. They need plain-language explanations, not numbers.
2. **No guided flow** — it's unclear where to start or what the steps are. The tabs feel disconnected rather than part of a workflow.

## Users

- **Primary (A):** CRO or sales leader who needs to review accounts and approve comments. Doesn't care about scoring internals — wants clear recommendations.
- **Secondary (B):** RevOps/strategy person who wants to understand and validate the scoring logic before trusting it.

## Goal

Make the app immediately understandable for a CRO on first use. Within 10 seconds they should know: "here's the big picture" and "here's where to act first." Detailed scoring remains accessible for power users via a collapsible section.

---

## Design

### 1. Welcome Banner (app.py)

When data finishes loading, show an orientation banner at the top of the page (above the tabs). It appears only on first load and is dismissed via a session state flag.

**Content:**

> **Welcome to the Global Account Review Agent**
> Your portfolio has **X accounts** scored and prioritized. **Y critical** and **Z at-risk** need your attention. Start with the **Account Review** tab to review and approve CRO comments, then save back to Sheets.

- `X` = total accounts loaded (`len(scored_df)`)
- `Y` = count of P1 accounts (`(scored_df["attention_tier"] == "P1").sum()`)
- `Z` = count of P2 accounts (`(scored_df["attention_tier"] == "P2").sum()`)

**Behaviour:**
- Rendered as `st.info(...)` with a "Got it" button below it.
- Clicking "Got it" sets `st.session_state["welcome_dismissed"] = True` and calls `st.rerun()`.
- The banner does not appear if `welcome_dismissed` is already `True`.
- The banner does not appear if `scored_df` is empty or data loading failed.

**Placement:** In `app.py`, after `st.session_state["scored_df"]` is set, before the `st.tabs(...)` call.

---

### 2. Simplified Review Card (review_card.py)

Replace the current "scores-first" layout with a "story-first" layout.

**Current layout (top to bottom):**
1. Header (tier badge, region, account name, AE)
2. 4 metric boxes (ARR, NRR, Renewal, Health)
3. Caption with deal stage + NRR tier label
4. Threading + expansion badges (raw scores)
5. Tech Stake breakdown (expanded)
6. Risk & Opportunity flags (expanded)
7. CRO comment + regenerate button

**New layout (top to bottom):**

#### A. Header (unchanged)
- Tier badge, account name, AE, region/territory.

#### B. Risk Summary (new)
- A single plain-language sentence summarizing why this account matters.
- Generated deterministically from scoring data (not an LLM call).
- Rendered as a styled block: left-bordered div with muted background, italic text.
- Border colour matches tier: red for P1, orange for P2, green for P3.
- See Section 4 (Risk Summary Generator) for the generation logic.

#### C. Key Facts (simplified metrics)
- Implemented as two rows of `st.columns(2)` with `st.metric()` for each cell.
- Shows: **ARR**, **NRR**, **Renewal Date**, **Contacts** (exec contact count).
- Each cell: label (small, muted) + value (large, bold).
- NRR value is colour-coded: red if NRR < 90, yellow if 90 <= NRR < 100, green if NRR >= 100 (matches existing `_nrr_colour()` thresholds).
- No tier labels like "AT_RISK" or "HEALTHY" — just the numbers with colour.
- No deal stage caption, no NRR tier text.
- Contact count: read from `scoring.get("contact_count")`. Display `"N/A"` if the value is `None`.

#### D. CRO Comment (unchanged)
- `st.markdown("---")`
- Model label
- `st.text_area` with generated comment
- Regenerate button + regen count

#### E. Scoring Details (collapsed, new wrapper)
- A single `st.expander("Scoring Details", expanded=False)` containing everything that was previously shown expanded:
  - NRR badge with tier label (from `risk_badges.nrr_badge()`)
  - Threading badge + expansion badge (from `risk_badges.py`)
  - Tech Stake breakdown (from `tech_stake_chart.py`)
  - Risk & Opportunity flags (from `risk_badges.build_risk_flags()`)
  - Caption with deal stage, NRR tier, health score
- This section is for power users (RevOps) who want to validate scoring.
- All existing rendering code is reused — just moved inside the collapsed expander.

---

### 3. Left Panel: Primary Signal Line (review.py)

Add `primary_signal` as a third line on each account row in the left panel. This text is already computed by the scoring engine (stored in the `primary_signal` column of `scored_df`). It explains why the account received its tier.

**Current row (2 lines):**
- Line 1: tier badge + account name + status chip
- Line 2: AE name + NRR + renewal countdown + region

**New row (3 lines):**
- Line 1: tier badge + account name + status chip
- Line 2: AE name + NRR + renewal countdown + region
- Line 3: `primary_signal` text in muted italic (e.g., *"NRR critical + single-threaded"*)

**Styling for line 3:**
- Font size: 0.7rem
- Colour: `#94a3b8` (muted grey)
- Font style: italic
- Truncated with `text-overflow: ellipsis` if too long (single line, no wrap)

**Data source:** `str(row.get("primary_signal", ""))` — already available on every scored row. If empty or "N/A", line 3 is not rendered.

---

### 4. Risk Summary Generator (new file: ui/components/risk_summary.py)

A deterministic template function that turns scoring data + row data into a plain-language risk summary sentence.

**Function signature:**

```python
def build_risk_summary(row: pd.Series, scoring: dict) -> str:
```

**Logic:** Build the sentence by combining up to 3 relevant facts, prioritised by urgency:

| Priority | Condition | Fragment |
|---|---|---|
| 1 (highest) | NRR tier == CRITICAL | "Revenue is declining at {nrr}% NRR" |
| 2 | NRR tier == AT_RISK | "NRR is below target at {nrr}%" |
| 3 | Renewal < 90 days | "renewal in {days} days" |
| 4 | Threading == SINGLE | "only {count} executive contact on file" |
| 5 | Threading == DUAL | "only {count} executive contacts — needs a third" |
| 6 | Health score <= 2 | "health score is {health}" |
| 7 | Expansion == HIGH | "{channel_count} product channels are uncaptured or competitor-held" |
| 8 | NRR tier == HEALTHY | "NRR is stable at {nrr}%" |
| 9 | NRR tier == STRONG | "Strong growth at {nrr}% NRR" |
| 10 | Threading == MULTI | "well multi-threaded" |

**Assembly rules:**
- Select the top 2–3 applicable fragments (by priority order).
- **Exception:** If health score <= 2 (priority 6), always include it regardless of how many higher-priority fragments exist. This is because low health is a P1 hard override trigger — the CRO must see it.
- Join fragments with `, ` between the first and second; use ` — ` before the final fragment if there are 3.
- Capitalise the first fragment; end with a period.
- If no conditions match, return: "No major risk signals identified."

**Examples:**
- P1: `"Revenue is declining at 84% NRR with renewal in 28 days — only 1 executive contact on file."`
- P2: `"NRR is below target at 94%, only 2 executive contacts — needs a third. 6 product channels are uncaptured or competitor-held."`
- P3: `"Strong growth at 118% NRR, well multi-threaded."`

**Renewal days calculation:** Uses `pd.to_datetime(row.get("renewal_date"), errors="coerce")` minus `pd.Timestamp.now()`. If parsing fails, the renewal fragment is skipped.

**Health score:** Read from `row.get("health_score")` (not from the `scoring` dict). Parse with `float()`; treat non-numeric values, NaN, or empty strings as absent (skip the health fragment).

**Contact count:** From `scoring.get("contact_count")`. If `None`, skip the threading fragment. Uses singular "contact" for count == 1, plural "contacts" otherwise.

**Channel count for expansion:** Sum of lengths of `scoring.get("competitor_channels", [])` and `scoring.get("whitespace_channels", [])`. Assumes these are Python lists. If they are strings (e.g., from CSV deserialization), the caller or `build_risk_summary` must deserialize them first via `ast.literal_eval`. Note: `_extract_scoring_from_row()` in `comment_generator.py` already handles this deserialization.

---

## Files Modified

| File | Change |
|---|---|
| `app.py` | Add welcome banner (dismissible `st.info` + "Got it" button) after data load, before tabs |
| `ui/components/review_card.py` | Reorder layout: header → risk summary → key facts (2x2) → CRO comment → collapsed scoring details expander |
| `ui/components/risk_summary.py` | **New file.** `build_risk_summary(row, scoring) -> str` — deterministic plain-language summary |
| `pages/review.py` | Add `primary_signal` as third line in left panel account rows |
| `ui/styles/custom.css` | Add `.risk-summary` style (see below) |

### CSS: Risk Summary

```css
.risk-summary {
    border-left: 4px solid;
    background: #1e293b;
    padding: 0.75rem 1rem;
    font-style: italic;
    font-size: 0.9rem;
    color: #cbd5e1;
    border-radius: 0 6px 6px 0;
    margin-bottom: 0.75rem;
}
```

Border colour is set inline per tier: `border-left-color: #dc3545` (P1), `#fd7e14` (P2), `#198754` (P3).

## What Does Not Change

| Area | Status |
|---|---|
| Scoring engine (`src/scoring/`) | Untouched |
| LLM / comment generation (`src/llm/`) | Untouched |
| Session persistence (`src/session/`) | Untouched |
| Google Sheets write-back | Untouched |
| Dashboard tab | Untouched |
| Report tab | Untouched |
| Two-panel layout structure | Untouched |
| Left panel search/filter/progress | Untouched |
| Sidebar filters | Untouched |

## Out of Scope

- Onboarding wizard or multi-step tutorial
- Tooltips or inline help system
- Changes to scoring weights or tier logic
- Dashboard simplification (separate effort)
- Dark/light mode toggle
