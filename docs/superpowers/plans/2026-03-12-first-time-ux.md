# First-Time UX Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the review flow immediately understandable for first-time CRO users by adding a welcome banner, simplifying review cards to "story-first" layout, and surfacing primary signals in the account list.

**Architecture:** Four independent changes — (1) a deterministic risk summary generator, (2) a simplified review card layout, (3) a welcome banner in app.py, (4) primary signal line in the left panel. The risk summary generator is a new file with no dependencies beyond pandas; the other three are modifications to existing files.

**Tech Stack:** Python 3.9, Streamlit, pandas

**Spec:** `docs/superpowers/specs/2026-03-12-first-time-ux-design.md`

---

## File Structure

| File | Role | Action |
|---|---|---|
| `ui/components/risk_summary.py` | Deterministic plain-language risk summary from scoring data | **Create** |
| `ui/components/review_card.py` | Account detail card in right panel | **Modify** — reorder to story-first layout |
| `ui/styles/custom.css` | Custom Streamlit styles | **Modify** — add `.risk-summary` class |
| `app.py` | Main entry point | **Modify** — add welcome banner |
| `pages/review.py` | Two-panel review page | **Modify** — add primary_signal line to left panel rows |
| `tests/test_risk_summary.py` | Unit tests for risk summary generator | **Create** |

---

## Chunk 1: Risk Summary Generator + Tests

### Task 1: Create risk summary generator with tests

**Files:**
- Create: `ui/components/risk_summary.py`
- Create: `tests/test_risk_summary.py`

- [ ] **Step 1: Write tests for the risk summary generator**

Create `tests/test_risk_summary.py`:

```python
"""Tests for the deterministic risk summary generator."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import pytest
from ui.components.risk_summary import build_risk_summary


def _make_row(**overrides):
    """Create a minimal account row Series with sensible defaults."""
    defaults = {
        "account_name": "Test Corp",
        "region": "APAC",
        "ae_name": "Jane Doe",
        "renewal_date": "2027-01-01",
        "health_score": "5",
    }
    defaults.update(overrides)
    return pd.Series(defaults)


def _make_scoring(**overrides):
    """Create a minimal scoring dict with sensible defaults."""
    defaults = {
        "nrr_tier": "HEALTHY",
        "nrr_display": "102%",
        "threading_tier": "MULTI",
        "contact_count": 4,
        "expansion_tier": "LOW",
        "competitor_channels": [],
        "whitespace_channels": [],
        "attention_tier": "P3",
    }
    defaults.update(overrides)
    return defaults


class TestBuildRiskSummary:
    def test_p1_critical_nrr_single_threaded(self):
        row = _make_row(renewal_date="2026-04-01")
        scoring = _make_scoring(
            nrr_tier="CRITICAL", nrr_display="84%",
            threading_tier="SINGLE", contact_count=1,
            attention_tier="P1",
        )
        result = build_risk_summary(row, scoring)
        assert "84%" in result
        assert "1 executive contact" in result
        assert result.endswith(".")

    def test_p2_at_risk_with_expansion(self):
        scoring = _make_scoring(
            nrr_tier="AT_RISK", nrr_display="94%",
            threading_tier="DUAL", contact_count=2,
            expansion_tier="HIGH",
            competitor_channels=[{"channel": "CDP", "vendor": "Segment"}],
            whitespace_channels=["SMS", "WhatsApp", "Email"],
            attention_tier="P2",
        )
        result = build_risk_summary(_make_row(), scoring)
        assert "94%" in result
        assert "4 product channels" in result

    def test_p3_strong_healthy(self):
        scoring = _make_scoring(
            nrr_tier="STRONG", nrr_display="118%",
            threading_tier="MULTI", contact_count=5,
            attention_tier="P3",
        )
        result = build_risk_summary(_make_row(), scoring)
        assert "118%" in result
        assert "multi-threaded" in result

    def test_no_signals_returns_default(self):
        scoring = _make_scoring(
            nrr_tier="UNKNOWN", threading_tier="UNKNOWN",
            expansion_tier="LOW",
        )
        result = build_risk_summary(_make_row(), scoring)
        assert result == "No major risk signals identified."

    def test_low_health_always_included(self):
        row = _make_row(health_score="1")
        scoring = _make_scoring(
            nrr_tier="CRITICAL", nrr_display="80%",
            threading_tier="SINGLE", contact_count=1,
            attention_tier="P1",
        )
        result = build_risk_summary(row, scoring)
        assert "health" in result.lower()

    def test_renewal_under_90_days(self):
        # Set renewal to 30 days from now
        future = (pd.Timestamp.now() + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        row = _make_row(renewal_date=future)
        scoring = _make_scoring(
            nrr_tier="AT_RISK", nrr_display="91%",
            attention_tier="P2",
        )
        result = build_risk_summary(row, scoring)
        assert "renewal" in result.lower()

    def test_contact_count_none_skips_threading(self):
        scoring = _make_scoring(
            nrr_tier="AT_RISK", nrr_display="92%",
            threading_tier="SINGLE", contact_count=None,
            attention_tier="P2",
        )
        result = build_risk_summary(_make_row(), scoring)
        assert "contact" not in result.lower()

    def test_string_channel_lists_handled(self):
        scoring = _make_scoring(
            nrr_tier="AT_RISK", nrr_display="93%",
            expansion_tier="HIGH",
            competitor_channels="[{'channel': 'CDP', 'vendor': 'Segment'}]",
            whitespace_channels="['SMS', 'WhatsApp']",
            attention_tier="P2",
        )
        result = build_risk_summary(_make_row(), scoring)
        assert "3 product channels" in result

    def test_result_ends_with_period(self):
        scoring = _make_scoring(nrr_tier="STRONG", nrr_display="115%")
        result = build_risk_summary(_make_row(), scoring)
        assert result.endswith(".")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m pytest tests/test_risk_summary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui.components.risk_summary'`

- [ ] **Step 3: Implement the risk summary generator**

Create `ui/components/risk_summary.py`:

```python
"""
Deterministic plain-language risk summary generator.

Turns scoring data + row data into a single human-readable sentence
explaining why an account matters. Not an LLM call — pure template logic.
"""

import ast
from typing import List

import pandas as pd


def build_risk_summary(row: pd.Series, scoring: dict) -> str:
    """
    Build a 1-2 sentence plain-language risk summary from scoring data.

    Args:
        row: Account row from the scored master DataFrame.
        scoring: Scoring results dict for this row.

    Returns:
        A human-readable sentence summarising the account's risk profile.
    """
    fragments: List[str] = []
    must_include: List[str] = []

    nrr_tier = scoring.get("nrr_tier", "UNKNOWN")
    nrr_display = str(scoring.get("nrr_display", "N/A")).replace("%", "").strip()
    threading_tier = scoring.get("threading_tier", "UNKNOWN")
    contact_count = scoring.get("contact_count")
    expansion_tier = scoring.get("expansion_tier", "LOW")

    # Priority 1: NRR CRITICAL
    if nrr_tier == "CRITICAL":
        fragments.append(f"Revenue is declining at {nrr_display}% NRR")

    # Priority 2: NRR AT_RISK
    elif nrr_tier == "AT_RISK":
        fragments.append(f"NRR is below target at {nrr_display}%")

    # Priority 3: Renewal < 90 days
    renewal_days = _renewal_days(row)
    if renewal_days is not None and renewal_days < 90:
        fragments.append(f"renewal in {renewal_days} days")

    # Priority 4-5: Threading
    if contact_count is not None:
        contact_word = "contact" if contact_count == 1 else "contacts"
        if threading_tier == "SINGLE":
            fragments.append(
                f"only {contact_count} executive {contact_word} on file"
            )
        elif threading_tier == "DUAL":
            fragments.append(
                f"only {contact_count} executive {contact_word} \u2014 needs a third"
            )

    # Priority 6: Low health (must-include — P1 hard override trigger)
    health = _parse_health(row)
    if health is not None and health <= 2:
        must_include.append(f"health score is {health:.0f}")

    # Priority 7: Expansion HIGH
    if expansion_tier == "HIGH":
        channel_count = _count_channels(scoring)
        if channel_count > 0:
            fragments.append(
                f"{channel_count} product channels are uncaptured or competitor-held"
            )

    # Priority 8-9: Positive NRR (only if no negative NRR fragment already added)
    if nrr_tier not in ("CRITICAL", "AT_RISK", "UNKNOWN"):
        if nrr_tier == "STRONG":
            fragments.append(f"Strong growth at {nrr_display}% NRR")
        elif nrr_tier == "HEALTHY":
            fragments.append(f"NRR is stable at {nrr_display}%")

    # Priority 10: Well multi-threaded
    if threading_tier == "MULTI":
        fragments.append("well multi-threaded")

    # Take top 3 fragments + always include must-includes
    selected = fragments[:3]
    for mi in must_include:
        if mi not in selected:
            selected.append(mi)

    if not selected:
        return "No major risk signals identified."

    return _assemble(selected)


def _assemble(fragments: List[str]) -> str:
    """Join fragments into a natural sentence."""
    if len(fragments) == 1:
        sentence = fragments[0]
    elif len(fragments) == 2:
        sentence = f"{fragments[0]}, {fragments[1]}"
    else:
        sentence = f"{fragments[0]}, {fragments[1]} \u2014 {fragments[2]}"
        if len(fragments) > 3:
            sentence += ", " + ", ".join(fragments[3:])

    # Capitalise first letter, ensure period
    sentence = sentence[0].upper() + sentence[1:]
    if not sentence.endswith("."):
        sentence += "."
    return sentence


def _renewal_days(row: pd.Series):
    """Return days until renewal, or None if unparseable."""
    try:
        rd = pd.to_datetime(row.get("renewal_date"), errors="coerce")
        if pd.isna(rd):
            return None
        return (rd - pd.Timestamp.now()).days
    except Exception:
        return None


def _parse_health(row: pd.Series):
    """Return health_score as float, or None if missing/non-numeric."""
    raw = row.get("health_score", "")
    try:
        val = float(str(raw).strip())
        if pd.isna(val):
            return None
        return val
    except (ValueError, TypeError):
        return None


def _count_channels(scoring: dict) -> int:
    """Count competitor + whitespace channels, handling string-encoded lists."""
    competitors = scoring.get("competitor_channels", [])
    whitespace = scoring.get("whitespace_channels", [])

    if isinstance(competitors, str):
        try:
            competitors = ast.literal_eval(competitors)
        except Exception:
            competitors = []
    if isinstance(whitespace, str):
        try:
            whitespace = ast.literal_eval(whitespace)
        except Exception:
            whitespace = []

    return len(competitors) + len(whitespace)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m pytest tests/test_risk_summary.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add ui/components/risk_summary.py tests/test_risk_summary.py
git commit -m "feat: add deterministic risk summary generator with tests"
```

---

## Chunk 2: Review Card Redesign + CSS

### Task 2: Simplify review card layout and add CSS

**Files:**
- Modify: `ui/components/review_card.py`
- Modify: `ui/styles/custom.css`

- [ ] **Step 1: Add `.risk-summary` CSS class**

Append to `ui/styles/custom.css`:

```css
/* ── Risk summary (story-first card) ─────────────────────────────────────── */
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

- [ ] **Step 2: Rewrite `render_review_card` in `ui/components/review_card.py`**

The new layout order is:

1. **Header** (unchanged) — tier badge, account name, AE, region/territory
2. **Risk Summary** (new) — call `build_risk_summary(row, scoring)`, render in a `.risk-summary` div with tier-coloured left border
3. **Key Facts** (simplified) — 2 rows of `st.columns(2)` with `st.metric()`: ARR, NRR, Renewal Date, Contacts. NRR label coloured via `_nrr_colour()` helper. Contacts shows "N/A" if `scoring.get("contact_count")` is `None`.
4. **CRO Comment** (unchanged) — divider, model label, text area, regenerate button
5. **Scoring Details** (collapsed) — single `st.expander("Scoring Details", expanded=False)` containing: NRR badge, threading badge, expansion badge, tech stake chips, risk flags, caption with deal stage + NRR tier + health score

Replace the full body of `render_review_card()` (lines 48–142) with:

```python
def render_review_card(
    row: pd.Series,
    scoring: dict,
    account_key: str,
    generated_comment: str,
    on_regenerate,
    approved_count: int = 0,
    model: str = "claude-sonnet-4-6",
) -> str:
    load_css()

    account_name = str(row.get("account_name", "Unknown")).strip()
    region = str(row.get("region", "")).strip()
    ae_name = str(row.get("ae_name", "N/A")).strip() or "N/A"
    territory = str(row.get("territory", "")).strip()
    attention_tier = scoring.get("attention_tier", "P2")
    nrr_display = scoring.get("nrr_display", "N/A")
    nrr_tier = scoring.get("nrr_tier", "UNKNOWN")

    # ── A. Header (unchanged) ──────────────────────────────────────────
    tier_html = attention_tier_badge(attention_tier)
    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center;
                    padding-bottom:0.75rem; margin-bottom:0.75rem;
                    border-bottom:1px solid #2d2d4a;">
            <div>{tier_html}
                 <span style="margin-left:0.75rem; color:#9ca3af; font-size:0.85rem;">
                     {region}
                 </span>
            </div>
        </div>
        <h2 style="margin:0 0 0.15rem 0; font-size:1.35rem; color:#e2e8f0;">{account_name}</h2>
        <div style="color:#9ca3af; font-size:0.85rem; margin-bottom:0.75rem;">
            AE: <strong style="color:#e2e8f0;">{ae_name}</strong>
            {"&nbsp;·&nbsp; " + territory if territory else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── B. Risk Summary (new) ──────────────────────────────────────────
    from ui.components.risk_summary import build_risk_summary
    summary_text = build_risk_summary(row, scoring)
    tier_border = {"P1": "#dc3545", "P2": "#fd7e14", "P3": "#198754"}.get(
        attention_tier, "#6c757d"
    )
    st.markdown(
        f'<div class="risk-summary" style="border-left-color:{tier_border}">'
        f'{summary_text}</div>',
        unsafe_allow_html=True,
    )

    # ── C. Key Facts (simplified 2x2) ─────────────────────────────────
    arr_display = _fmt_currency(row.get("arr"))
    renewal_date = str(row.get("renewal_date", "N/A")).strip() or "N/A"
    contact_count = scoring.get("contact_count")
    contact_display = str(contact_count) if contact_count is not None else "N/A"

    r1c1, r1c2 = st.columns(2)
    r1c1.metric("ARR", arr_display)
    r1c2.metric("NRR", str(nrr_display))
    r2c1, r2c2 = st.columns(2)
    r2c1.metric("Renewal", renewal_date)
    r2c2.metric("Contacts", contact_display)

    # ── D. CRO Comment (unchanged) ────────────────────────────────────
    st.markdown("---")
    st.markdown(f"**CRO Suggested Comment** *({model})*")

    comment_area_key = f"comment_area_{account_key}"
    regen_count_key = f"regen_{account_key}"

    if comment_area_key not in st.session_state:
        st.session_state[comment_area_key] = generated_comment

    edited_comment = st.text_area(
        "Edit before approving:",
        value=st.session_state[comment_area_key],
        height=140,
        key=comment_area_key,
        help="The AI-generated comment. Modify freely before approving.",
    )

    if st.button("Regenerate", key=f"regen_btn_{account_key}"):
        st.session_state[regen_count_key] = st.session_state.get(regen_count_key, 0) + 1
        on_regenerate()

    regen_count = st.session_state.get(regen_count_key, 0)
    if regen_count > 0:
        st.caption(f"Regenerated {regen_count} time(s)")

    # ── E. Scoring Details (collapsed) ────────────────────────────────
    with st.expander("Scoring Details", expanded=False):
        # NRR badge
        st.markdown(nrr_badge(nrr_display, nrr_tier), unsafe_allow_html=True)
        # Threading + expansion badges
        badges_html = (
            threading_badge(scoring.get("threading_tier", "UNKNOWN"), scoring.get("contact_count"))
            + "&nbsp;&nbsp;"
            + expansion_badge(scoring.get("expansion_tier", "LOW"), float(scoring.get("expansion_score", 0) or 0))
        )
        st.markdown(f"<div style='margin:0.5rem 0;'>{badges_html}</div>", unsafe_allow_html=True)
        # Tech Stake
        st.markdown(render_channel_chips(scoring), unsafe_allow_html=True)
        # Risk flags
        st.markdown(build_risk_flags(scoring), unsafe_allow_html=True)
        # Caption with deal stage, NRR tier, health
        health_raw = str(row.get("health_score", "")).strip()
        health_display = health_raw if health_raw and health_raw not in ("nan", "") else "N/A"
        deal_stage = str(row.get("deal_stage", "N/A")).strip() or "N/A"
        st.caption(f"**Stage:** {deal_stage} | **NRR Tier:** {nrr_tier} | **Health:** {health_display}")

    return edited_comment
```

Note: add `nrr_badge` to the import from `risk_badges` at the top of the file.

- [ ] **Step 3: Verify syntax**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m py_compile ui/components/review_card.py && python3 -m py_compile ui/styles/custom.css 2>/dev/null; echo "OK"`

- [ ] **Step 4: Commit**

```bash
git add ui/components/review_card.py ui/styles/custom.css
git commit -m "feat: simplify review card to story-first layout with collapsed scoring details"
```

---

## Chunk 3: Welcome Banner + Left Panel Signal

### Task 3: Add welcome banner to app.py

**Files:**
- Modify: `app.py:78-98`

- [ ] **Step 1: Add welcome banner after data load**

In `app.py`, after `st.session_state["scored_df"] = scored_df` (line 86) and before the tab navigation (line 100), insert:

```python
    # Welcome banner — shown once per session for first-time orientation
    if not st.session_state.get("welcome_dismissed"):
        scored_df_local = st.session_state["scored_df"]
        total = len(scored_df_local)
        p1 = int((scored_df_local["attention_tier"] == "P1").sum()) if "attention_tier" in scored_df_local.columns else 0
        p2 = int((scored_df_local["attention_tier"] == "P2").sum()) if "attention_tier" in scored_df_local.columns else 0
        st.info(
            f"**Welcome to the Global Account Review Agent**\n\n"
            f"Your portfolio has **{total} accounts** scored and prioritized. "
            f"**{p1} critical** and **{p2} at-risk** need your attention. "
            f"Start with the **Account Review** tab to review and approve CRO comments, "
            f"then save back to Sheets."
        )
        if st.button("Got it", key="dismiss_welcome"):
            st.session_state["welcome_dismissed"] = True
            st.rerun()
```

- [ ] **Step 2: Verify syntax**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m py_compile app.py && echo "OK"`

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: add dismissible welcome banner with portfolio summary"
```

### Task 4: Add primary_signal to left panel rows

**Files:**
- Modify: `pages/review.py` (inside `_render_left_panel`, the `row_html` template)

- [ ] **Step 1: Extract primary_signal from row data**

In `pages/review.py`, inside the `for idx, key in enumerate(filtered_keys):` loop in `_render_left_panel`, after the existing `region = str(row.get("region", "")).strip()` line, add:

```python
            primary_signal = str(row.get("primary_signal", "")).strip()
            primary_signal = primary_signal if primary_signal.lower() not in ("nan", "n/a", "none", "") else ""
```

- [ ] **Step 2: Add line 3 to the row_html template**

In the `row_html` f-string, after the closing `</div>` of the second `<div>` (the NRR/renewal/region line), add a third line:

```python
              {'<div style="font-size:0.7rem;color:#94a3b8;font-style:italic;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px">' + primary_signal + '</div>' if primary_signal else ''}
```

- [ ] **Step 3: Verify syntax**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m py_compile pages/review.py && echo "OK"`

- [ ] **Step 4: Commit**

```bash
git add pages/review.py
git commit -m "feat: show primary_signal as third line in left panel account rows"
```

---

## Chunk 4: Integration Verification

### Task 5: End-to-end verification

- [ ] **Step 1: Run all tests**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Syntax check all modified files**

Run: `cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m py_compile app.py && python3 -m py_compile pages/review.py && python3 -m py_compile ui/components/review_card.py && python3 -m py_compile ui/components/risk_summary.py && echo "All OK"`

- [ ] **Step 3: Restart Streamlit and verify visually**

Run:
```bash
lsof -ti :8504 | xargs kill -9 2>/dev/null
sleep 2
cd "/Users/elifbikmaz/Desktop/project dolly" && python3 -m streamlit run app.py --server.port 8504
```

Verify in browser at `http://localhost:8504`:
1. Welcome banner appears with correct account counts and "Got it" button
2. Clicking "Got it" dismisses it permanently
3. Review tab: account cards show risk summary sentence at top, key facts in 2x2 grid
4. Scoring details are collapsed by default, expandable
5. Left panel rows show primary_signal as italic third line
6. Comment generation, approve, skip, save all still work
