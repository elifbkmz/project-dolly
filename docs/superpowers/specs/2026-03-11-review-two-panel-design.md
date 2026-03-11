# Review Page: Two-Panel Layout Redesign

**Date:** 2026-03-11
**Status:** Approved
**Scope:** `pages/review.py`, `ui/components/review_card.py`

---

## Problem

The current review flow is single-account-at-a-time: the user sees one card, acts on it, and the page reruns to show the next. This makes it hard to:
- Scan the full account list and prioritise where to spend time
- Batch-approve low-risk accounts without clicking through each one
- See context (NRR, renewal, region) without opening every card

## Goal

Redesign the Review tab as a two-panel split: a persistent scrollable account list on the left, and the selected account's detail card on the right. Approve/Skip buttons live at the bottom of the detail panel. Users can click any row to jump to any account non-linearly.

---

## Design

### Layout

Replace the current single-column card loop with `st.columns([1, 2])`:

- **Left column (1/3 width):** Account list panel
- **Right column (2/3 width):** Detail card for selected account

Selection state: `st.session_state["selected_account_key"]` — stores the canonical `account_key` string (not an index) for the currently selected account. This is stable across filter changes. Defaults to the first account in the filtered list on initial load.

---

### Left Panel — Account List

**Header row:**
- "Accounts" label + total count badge
- "X done" progress indicator (approved + skipped count)
- Search input (filters displayed rows by account name substring match, case-insensitive, stored in `st.session_state["list_search"]`)
- Tier filter pill (All / P1 / P2 / P3, stored in `st.session_state["list_tier_filter"]`)

**Scrollability:** The account list is rendered inside a fixed-height container using `st.container(height=...)`. The selected row does not auto-scroll into view (Streamlit does not support this natively); the user scrolls manually. The selected row is visually distinguished by blue left-border and highlighted background.

**Each account row** (two lines, rendered as a `st.button` with `use_container_width=True`):
- Line 1: P-tier badge (colour-coded) · account name · status chip (pending / ✓ approved / – skipped)
- Line 2: NRR % (red < 90, yellow 90–99, green ≥ 100) · renewal countdown (e.g. `↻ 47d`) · region

Clicking a row sets `st.session_state["selected_account_key"]` to that account's key and calls `st.rerun()`.

**Left-border colour per row:**
- Blue — currently selected
- Green — approved
- Orange — skipped (explicitly skipped by user)
- No accent — pending (not yet visited)

**Empty state:** If the search + tier filter combination returns zero accounts, the left panel shows a centred message: `"No accounts match your filters."` The right panel shows a placeholder: `"Select an account from the list."` No error is raised.

**Footer:** Progress bar showing `(approved + skipped) / total_unfiltered`.

---

### Right Panel — Detail Card

**Model selector + info banner:** The existing model selector (Sonnet vs Opus) and account-count banner move to the top of the right panel, above the account header. This keeps them visible without consuming left panel space.

**Header:**
- P-tier badge · account name · AE name · region
- NRR % and renewal days (right-aligned)

**Score pills row:**
- Composite score (numeric)
- NRR tier (CRITICAL / AT_RISK / HEALTHY / STRONG)
- Threading tier (SINGLE / DUAL / MULTI)
- Expansion tier (HIGH / MEDIUM / LOW)
- Primary signal explanation text (italic, fills remaining width)

**Comment section:**

The comment is displayed in a persistent `st.text_area` (always editable, matching current behaviour in `review_card.py`). There is no read-only/edit toggle. The "Edit" button is removed. Only Regenerate remains alongside the text area.

Comment generation on account selection:
- If the selected account already has a generated comment in session state, it is shown immediately.
- If not, the right panel shows a spinner (`st.spinner("Generating comment…")`) and generates the comment for that account on demand (blocking, same as today). The left panel remains interactive during this wait because Streamlit reruns complete before the next interaction.
- If the user clicks a different account while generation is in progress: generation is not cancellable in Streamlit's synchronous model — the rerun will complete the current generation, then the newly selected account will render. No special handling needed; this is acceptable UX for v1.

Comment state key: `f"comment_area_{account_key}"` — keyed by `account_key` (not position). This ensures state persists correctly when the user navigates away and returns to the same account, and survives filter changes.

The regenerate handler in `review.py` must also be updated to read and write using `f"comment_area_{account_key}"`. No migration of old position-based keys is required — on first load under the new code, if no comment exists under the new key, it is generated fresh (same as a new session).

**Action bar (pinned to bottom of panel):**
- `✓ Approve` button (green, prominent)
- `– Skip` button (grey)
- `Save to Master Sheets` button (existing write-back button, moved here from the old card footer — same behaviour, no logic changes)
- Keyboard nav hint: `← → to navigate`

Approve/Skip behaviour is identical to current implementation — writes to `st.session_state` decisions dict and auto-saves session JSON. After Approve or Skip, `selected_account_key` automatically advances to the next **pending** (undecided) account in the current left-panel filtered list (respecting both `list_search` and `list_tier_filter`). If no pending account remains in the filtered list, show a completion banner in the right panel: `"All filtered accounts reviewed. Change filters or return to the dashboard."` — do not cycle back.

---

### Filter Change Handling

The filtered account list preserves the original `review_order` from the session (i.e., sorted by composite score descending, P1 first). "First account" always means the first account in that ordering within the current filter scope.

When `list_search` or `list_tier_filter` changes:
- If `selected_account_key` is still present in the new filtered list, keep it selected.
- If `selected_account_key` is no longer in the filtered list (account filtered out), reset to the first account in the new filtered list. If the new filtered list is empty, set `selected_account_key` to `None` and show the empty state.

`list_search` persists independently of account selection — clearing or changing the search string does not reset the selected account (subject to the above rule). The left panel always reflects the current search + tier filter, and the selected account remains highlighted if it appears in the filtered results.

**Progress bar denominator:** `total_unfiltered` = `len(session.review_order)` — the total accounts in the session at load time, regardless of current left-panel search/tier filter. This matches the existing session progress semantics.

---

### Keyboard Navigation

Arrow keys (← →) update `selected_account_key` to the previous/next account in the current filtered list.

Implementation: inject a `st.components.v1.html` block with a JS event listener on `keydown`. On left/right arrow, the JS clicks a hidden `st.button` (labelled `__nav_prev__` / `__nav_next__`, rendered but visually hidden via CSS). The hidden buttons update `selected_account_key` in session state and call `st.rerun()`.

**Note:** This is a known Streamlit workaround with a known limitation — it requires the page to have focus and does not work if the user's cursor is inside a text area. The `← → to navigate` hint text is always shown. Users inside the text area will simply not get keyboard nav, which is acceptable for v1. If the hidden-button approach proves unreliable during implementation, keyboard nav is deferred and the hint text removed entirely — it is a nice-to-have, not a requirement.

---

---

### State Initialisation

The following `st.session_state` keys are initialised in `pages/review.py` inside the existing `_initialize_session()` function (or equivalent init block), with these defaults:

| Key | Type | Default |
|---|---|---|
| `selected_account_key` | `str \| None` | first key in `session.review_order` |
| `list_search` | `str` | `""` |
| `list_tier_filter` | `str` | `"All"` |

---

### `current_index` and Non-Linear Navigation

The existing `session.current_index` is used today to track sequential progress. In the new design it is repurposed to a **count of decided accounts** (`len(approved) + len(skipped)`), not a pointer into the list. It no longer drives which account is shown — `selected_account_key` does that.

The `record_decision()` call in session state continues to record decisions by `account_key` as before. The `current_index` increment in `record_decision()` is kept but its meaning shifts: it reflects the total number of decisions made, not the current position in the list. The progress bar and "X done" counter read from `current_index`.

---

### Sidebar Filters vs Left-Panel Filters

These are **additive** (AND logic):

1. **Sidebar filters** (region, AE, tier from `progress_sidebar.py`) filter the master `scored_df` into `session_df` — this is unchanged from today.
2. **Left-panel filters** (`list_search`, `list_tier_filter`) further filter `session_df` to produce the visible account list in the left panel.

The left-panel tier filter restricts within whatever the sidebar tier filter allows (e.g., sidebar = APAC only, left-panel tier = P1 only → shows APAC P1 accounts only). The "next pending account" advance logic and completion detection operate on the **left-panel filtered list** only.

---

## Files Modified

| File | Change |
|---|---|
| `pages/review.py` | Replace single-card loop with `st.columns([1, 2])` layout; add row-click selection logic; add filter-change handling; add hidden keyboard nav buttons; move model selector + info banner to top of right panel |
| `ui/components/review_card.py` | Change comment state key from `f"comment_area_{account_name}_{position}"` to `f"comment_area_{account_key}"`; remove full-page navigation wrappers (prev/next buttons, page counter); keep comment text area, regenerate button, score pills, and header — these are reused as-is inside the right panel |

No new files required.

---

## What Does Not Change

| Area | Status |
|---|---|
| Scoring engine | Untouched |
| Session persistence (`src/session/`) | Untouched |
| Google Sheets write-back logic | Untouched |
| Sidebar filters (region, AE, tier) | Still work — they feed into the same filtered DataFrame that the left panel list renders from |
| Comment generation logic (`src/llm/`) | Untouched |
| Dashboard and Report tabs | Untouched |

---

## Out of Scope

- Bulk-select checkboxes ("approve all P3")
- Drag-and-drop reordering
- Dark/light mode toggle
- Any changes to scoring, ingestion, or LLM logic
