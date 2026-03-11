# Review Page: Two-Panel Layout Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-card review flow with a two-panel layout — persistent account list on the left, detail card on the right — so users can batch-approve without navigating page by page.

**Architecture:** Two `st.columns([1, 2])` panels share a single `selected_account_key` in session state. The left panel renders all accounts as clickable rows; the right panel renders the full detail card for the selected account. Action buttons (Approve / Skip / Save) live at the bottom of the right panel. Selection state is key-based (not index-based) so it survives filter changes.

**Tech Stack:** Python 3.11, Streamlit 1.x, Pandas — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-03-11-review-two-panel-design.md`

---

## Chunk 1: State helpers and filter logic

**Files:**
- Modify: `pages/review.py` — add state initialisation keys and two helper functions

---

- [ ] **Step 1.1: Read the current `_initialize_session()` function**

  Open `pages/review.py` lines 298–337. Note that it already sets `st.session_state["active_filter"]` and `st.session_state["generated_comments"]`. We add three new keys here.

- [ ] **Step 1.2: Add the three new state keys to `_initialize_session()`**

  At the end of `_initialize_session()`, just before `st.rerun()`, add:

  ```python
  # Two-panel selection state
  # Note: review_order is already filtered by sidebar (region/AE/tier) at this point.
  # selected_account_key defaults to the first account in that sidebar-filtered order.
  st.session_state["selected_account_key"] = review_order[0] if review_order else None
  st.session_state["list_search"] = ""
  st.session_state["list_tier_filter"] = "All"
  ```

- [ ] **Step 1.3: Add `_get_filtered_account_list()` helper**

  Add this function near the bottom of `pages/review.py`, below `_find_account_row`:

  ```python
  def _get_filtered_account_list(
      scored_df: pd.DataFrame,
      session: "SessionState",
      list_search: str,
      list_tier_filter: str,
  ) -> list[str]:
      """
      Return account keys visible in the left panel, in review_order ordering.

      Applies left-panel filters (search + tier) on top of whatever sidebar
      filters already produced session.review_order.
      """
      search = list_search.strip().lower()
      keys = []
      for key in session.review_order:
          # Match key against scored_df to get tier and name
          row_df = _find_account_row(scored_df, key)
          if row_df is None:
              continue
          row = row_df.iloc[0]
          account_name = str(row.get("account_name", "")).lower()
          tier = str(row.get("attention_tier", ""))

          if search and search not in account_name:
              continue
          if list_tier_filter != "All" and tier != list_tier_filter:
              continue
          keys.append(key)
      return keys
  ```

  > **Note:** `_find_account_row` is O(n) per call. With typical account counts (< 500) this is fine for v1. Do not optimise unless you measure a real slowdown.

- [ ] **Step 1.4: Add `_next_pending_key()` helper**

  Add this function directly below `_get_filtered_account_list`:

  ```python
  def _next_pending_key(
      filtered_keys: list[str],
      current_key: str,
      decisions: dict,
  ) -> str | None:
      """
      Return the next key after current_key in filtered_keys that has no decision yet.

      `decisions` is session.decisions — a dict keyed by account_key.
      Returns None if no pending account exists after current_key in the list.
      """
      found_current = False
      for key in filtered_keys:
          if key == current_key:
              found_current = True
              continue
          if found_current and key not in decisions:
              return key
      # Wrap-search from beginning if not found after current
      for key in filtered_keys:
          if key == current_key:
              break
          if key not in decisions:
              return key
      return None
  ```

- [ ] **Step 1.5: Add `_resolve_selected_key()` helper**

  This handles filter-change edge cases (selected account filtered out):

  ```python
  def _resolve_selected_key(
      filtered_keys: list[str],
      current_selected: str | None,
  ) -> str | None:
      """
      Return current_selected if it is still in filtered_keys.
      Otherwise return the first key in filtered_keys, or None if empty.
      """
      if current_selected in filtered_keys:
          return current_selected
      return filtered_keys[0] if filtered_keys else None
  ```

- [ ] **Step 1.6: Run a quick syntax check**

  ```bash
  python -m py_compile pages/review.py
  ```

  Expected: no output (no errors).

- [ ] **Step 1.7: Commit**

  ```bash
  git add pages/review.py
  git commit -m "feat: add two-panel state helpers (filter list, next-pending, key resolver)"
  ```

---

## Chunk 2: Left panel component

**Files:**
- Modify: `pages/review.py` — add `_render_left_panel()` function

---

- [ ] **Step 2.1: Understand what data each row needs**

  Each row needs: `account_key`, `account_name`, `attention_tier`, `nrr_display`, `renewal_date`, `region`, and decision status (`approved` / `skipped` / `pending`).

  The NRR colour thresholds from the spec: red < 90, yellow 90–99, green ≥ 100. Parse `nrr_display` as a float (strip `%`, handle `N/A`).

- [ ] **Step 2.2: Add `_nrr_colour()` helper**

  Add near the bottom of `pages/review.py`:

  ```python
  def _nrr_colour(nrr_display: str) -> str:
      """Return a CSS hex colour for the NRR value. Red < 90, yellow 90-99, green >= 100."""
      try:
          val = float(str(nrr_display).replace("%", "").replace("N/A", "").strip())
          if val < 90:
              return "#f87171"   # red
          if val < 100:
              return "#fbbf24"   # yellow
          return "#4ade80"       # green
      except (ValueError, TypeError):
          return "#94a3b8"       # grey for N/A
  ```

- [ ] **Step 2.3: Add `_render_left_panel()` function**

  Add this function to `pages/review.py`:

  ```python
  def _render_left_panel(
      scored_df: pd.DataFrame,
      session: "SessionState",
  ) -> None:
      """
      Render the left-panel account list.

      Reads/writes:
        st.session_state["list_search"]
        st.session_state["list_tier_filter"]
        st.session_state["selected_account_key"]
      """
      decisions = session.decisions  # dict[account_key, AccountDecision]
      total = len(session.review_order)
      done = session.approved_count() + session.skipped_count()

      # ── Header ────────────────────────────────────────────────────────────
      st.markdown(
          f"**Accounts** &nbsp; "
          f"<span style='background:#334155;color:#94a3b8;font-size:0.75rem;"
          f"padding:1px 7px;border-radius:10px'>{total}</span>"
          f"&nbsp;&nbsp;"
          f"<span style='color:#4ade80;font-size:0.8rem'>{done} done</span>",
          unsafe_allow_html=True,
      )

      # ── Filters ────────────────────────────────────────────────────────────
      search = st.text_input(
          "Search accounts",
          value=st.session_state.get("list_search", ""),
          key="list_search",
          placeholder="filter by name…",
          label_visibility="collapsed",
      )
      tier_filter = st.radio(
          "Tier",
          options=["All", "P1", "P2", "P3"],
          index=["All", "P1", "P2", "P3"].index(
              st.session_state.get("list_tier_filter", "All")
          ),
          horizontal=True,
          key="list_tier_filter",
          label_visibility="collapsed",
      )

      # ── Build filtered list and resolve selection ──────────────────────────
      filtered_keys = _get_filtered_account_list(scored_df, session, search, tier_filter)
      selected_key = _resolve_selected_key(
          filtered_keys, st.session_state.get("selected_account_key")
      )
      # Persist resolved key (handles filter-change edge case)
      st.session_state["selected_account_key"] = selected_key

      # ── Empty state ────────────────────────────────────────────────────────
      if not filtered_keys:
          st.markdown(
              "<div style='text-align:center;color:#64748b;padding:2rem 0'>"
              "No accounts match your filters.</div>",
              unsafe_allow_html=True,
          )
          _render_left_panel_footer(done, total)
          return

      # ── Account rows ──────────────────────────────────────────────────────
      with st.container(height=480):
          for key in filtered_keys:
              row_df = _find_account_row(scored_df, key)
              if row_df is None:
                  continue
              row = row_df.iloc[0]

              account_name = str(row.get("account_name", key)).strip()
              tier = str(row.get("attention_tier", "P3"))
              nrr_display = str(row.get("nrr_display") or row.get("nrr") or "N/A")
              renewal_date = str(row.get("renewal_date", "N/A") or "N/A").strip()
              region = str(row.get("region", "")).strip()

              # Decision status
              decision = decisions.get(key)
              if decision and decision.status == "approved":
                  status_html = "<span style='color:#22c55e;font-size:0.75rem'>✓ approved</span>"
                  border_colour = "#22c55e"
              elif decision and decision.status == "skipped":
                  status_html = "<span style='color:#f97316;font-size:0.75rem'>– skipped</span>"
                  border_colour = "#f97316"
              else:
                  status_html = "<span style='color:#f59e0b;font-size:0.75rem'>pending</span>"
                  border_colour = "#3b82f6" if key == selected_key else "transparent"

              # Tier badge colour
              tier_colour = {"P1": "#ef4444", "P2": "#f59e0b", "P3": "#22c55e"}.get(tier, "#6b7280")
              nrr_colour = _nrr_colour(nrr_display)

              # Renewal days countdown
              # pd is already imported at the top of review.py — do NOT re-import here
              renewal_display = "N/A"
              try:
                  rd = pd.to_datetime(renewal_date, errors="coerce")
                  if not pd.isna(rd):
                      days = (rd - pd.Timestamp.now()).days
                      renewal_display = f"↻ {days}d" if days >= 0 else f"↻ {days}d (overdue)"
              except Exception:
                  renewal_display = renewal_date

              row_html = f"""
              <div style="
                  border-left: 3px solid {border_colour};
                  background: {'#0f3460' if key == selected_key else '#1e293b'};
                  border-radius: 4px;
                  padding: 7px 9px;
                  margin-bottom: 3px;
              ">
                <div style="display:flex;align-items:center;gap:6px">
                  <span style="background:{tier_colour};color:#fff;font-size:0.7rem;
                               padding:1px 5px;border-radius:2px;font-weight:bold">{tier}</span>
                  <span style="color:{'#fff' if key == selected_key else '#cbd5e1'};
                               font-size:0.85rem;font-weight:{'600' if key == selected_key else '400'}"
                  >{account_name}</span>
                  <span style="margin-left:auto">{status_html}</span>
                </div>
                <div style="display:flex;gap:10px;margin-top:3px">
                  <span style="color:{nrr_colour};font-size:0.75rem">NRR {nrr_display}</span>
                  <span style="color:#94a3b8;font-size:0.75rem">{renewal_display}</span>
                  <span style="color:#94a3b8;font-size:0.75rem">{region}</span>
                </div>
              </div>
              """

              # Invisible button overlaid on the visual row
              # st.button provides the click handler; HTML above provides the look
              if st.button(
                  account_name,
                  key=f"row_btn_{key}",
                  use_container_width=True,
              ):
                  st.session_state["selected_account_key"] = key
                  st.rerun()

              # Render HTML row (appears above the button visually via negative margin hack)
              # NOTE: In Streamlit, buttons render in flow order. We render the HTML
              # after the button — both are visible. Use CSS to visually hide the plain
              # button text and let the HTML row act as the visual.
              st.markdown(row_html, unsafe_allow_html=True)

      _render_left_panel_footer(done, total)


  def _render_left_panel_footer(done: int, total: int) -> None:
      progress = done / total if total > 0 else 0
      st.progress(progress)
      st.caption(f"{done} / {total} reviewed")
  ```

  > **Implementation note on button + HTML overlap:** Streamlit doesn't support custom-styled clickable containers natively. The pattern above renders an invisible `st.button` (whose label is just the account name) followed by a styled HTML block. The button captures clicks; the HTML provides visual richness. The button's own visual appearance will be visible beneath the HTML — add CSS to `ui/styles/custom.css` in Step 2.4 to suppress the default button appearance for row buttons.

- [ ] **Step 2.4: Add CSS for row buttons in `ui/styles/custom.css`**

  Open `ui/styles/custom.css`. Add at the end:

  ```css
  /* Two-panel review: hide default button text for account-row buttons.
     Streamlit buttons do NOT have a `kind` attribute in the DOM.
     Use data-testid on the wrapper div to target by key prefix. */
  div[data-testid="stButton"]:has(button[data-testid^="row_btn_"]) button {
      visibility: hidden;
      height: 0;
      min-height: 0;
      padding: 0;
      margin: 0;
      border: none;
  }
  ```

  > **Note:** The `:has()` CSS selector requires a modern browser (Chrome 105+, Safari 15.4+, Firefox 121+). If your target browser does not support it, accept the default button appearance for now — a plain text button will appear above each HTML row, but the functionality is unaffected. This is a known v1 visual limitation.

- [ ] **Step 2.5: Syntax check**

  ```bash
  python -m py_compile pages/review.py
  ```

  Expected: no output.

- [ ] **Step 2.6: Smoke test the left panel in isolation**

  Temporarily call `_render_left_panel(scored_df, session)` from `render_review_page()` just before the existing card render (we'll wire it properly in Chunk 4). Run the app:

  ```bash
  streamlit run app.py
  ```

  Navigate to the Review tab. Verify:
  - Account list renders with tier badges, NRR colour, renewal countdown, region.
  - Clicking a row updates `selected_account_key` in session state (check via Streamlit's built-in state viewer or a `st.write(st.session_state["selected_account_key"])` debug line).
  - Search box filters the list in real time.
  - Tier radio filters correctly.
  - Progress bar and "X done" update after an approve/skip action.

  Remove the temporary call before committing.

- [ ] **Step 2.7: Commit**

  ```bash
  git add pages/review.py ui/styles/custom.css
  git commit -m "feat: add left panel account list with search, tier filter, and progress bar"
  ```

---

## Chunk 3: Refactor `review_card.py` for key-based state

**Files:**
- Modify: `ui/components/review_card.py`

The goal of this chunk is to update `review_card.py` so it:
1. Keys comment state by `account_key` instead of `(account_name, position)`.
2. Removes the position counter from the card header (position is now shown in the left panel).
3. Removes the full-page prev/next navigation (there isn't any currently, but we remove the `position` / `total` parameters since they're no longer needed).
4. Removes the action buttons from the card — they move to the right panel action bar in Chunk 4.

---

- [ ] **Step 3.1: Update `render_review_card()` signature**

  Change the function signature from:

  ```python
  def render_review_card(
      row: pd.Series,
      scoring: dict,
      position: int,
      total: int,
      generated_comment: str,
      on_approve,
      on_regenerate,
      on_skip,
      on_save_to_master,
      approved_count: int = 0,
  ) -> None:
  ```

  To:

  ```python
  def render_review_card(
      row: pd.Series,
      scoring: dict,
      account_key: str,
      generated_comment: str,
      on_regenerate,
      approved_count: int = 0,
  ) -> str:
      """
      Render the account detail section (header, metrics, badges, tech stake,
      risk flags, comment text area).

      Returns the current text in the comment text area (may be edited by user).
      Action buttons (Approve, Skip, Save) are rendered by the caller.
      """
  ```

  > We remove `position`, `total`, `on_approve`, `on_skip`, `on_save_to_master` from the card — those actions move to the right-panel action bar in `review.py`. The card now only owns the display and the comment editor.

- [ ] **Step 3.2: Update the card header — remove position counter**

  In the header block (around line 72), change:

  ```python
  region_meta = f"{region} &nbsp;·&nbsp; Account {position} of {total}"
  ```

  To:

  ```python
  region_meta = region
  ```

- [ ] **Step 3.3: Update comment state keys to use `account_key`**

  Change lines 128–129 from:

  ```python
  comment_area_key = f"comment_area_{account_name}_{position}"
  regen_count_key = f"regen_{account_name}_{position}"
  ```

  To:

  ```python
  comment_area_key = f"comment_area_{account_key}"
  regen_count_key = f"regen_{account_key}"
  ```

- [ ] **Step 3.4: Replace the action buttons block with Regenerate + return**

  Replace the entire action buttons block (lines 152–175, from `# ── Pending save banner` to the end of `render_review_card`) with:

  ```python
  # ── Regenerate button ─────────────────────────────────────────────────
  if st.button("🔄 Regenerate", key=f"regen_btn_{account_key}"):
      st.session_state[regen_count_key] = st.session_state.get(regen_count_key, 0) + 1
      on_regenerate()

  regen_count = st.session_state.get(regen_count_key, 0)
  if regen_count > 0:
      st.caption(f"🔄 Regenerated {regen_count} time(s)")

  return edited_comment
  ```

  The `b1, b2, b3, b4 = st.columns(...)` layout and all four old buttons (Approve, Regenerate, Skip, Save) are removed entirely. Approve, Skip, and Save move to the action bar in `_render_right_panel()` (Chunk 4). Only Regenerate stays in the card.

- [ ] **Step 3.5: Add `model` parameter and use it for the comment label**

  Add `model: str = "claude-sonnet-4-6"` to the `render_review_card()` signature (after `approved_count`):

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
  ```

  Then change the hardcoded label on line 125 to use the passed-in parameter:

  ```python
  st.markdown(f"**🤖 CRO Suggested Comment** *({model})*")
  ```

  In Chunk 4, pass `model=model` when calling `render_review_card()` so the label accurately reflects the model that generated the visible comment (not the currently-selected dropdown value, which may differ if the user just changed it).

- [ ] **Step 3.6: Syntax check**

  ```bash
  python -m py_compile ui/components/review_card.py
  ```

  Expected: no output.

- [ ] **Step 3.7: Commit**

  ```bash
  git add ui/components/review_card.py
  git commit -m "refactor: key review card comment state by account_key, remove nav/action buttons from card"
  ```

---

## Chunk 4: Wire the two-panel layout in `review.py`

**Files:**
- Modify: `pages/review.py` — replace the main render body with the two-column layout

This is the main wiring chunk. We replace the old single-card `render_review_page()` body with the two-panel flow.

---

- [ ] **Step 4.1: Update `_handle_regenerate()` to use `account_key`-based state key**

  Change line 189 from:

  ```python
  st.session_state[f"comment_area_{account_name}_{position}"] = new_comment
  ```

  To:

  ```python
  st.session_state[f"comment_area_{account_key}"] = new_comment
  ```

  Also remove these two lines that are no longer valid in the new design:

  ```python
  account_name = str(row.get("account_name", ""))
  position = st.session_state["session"].current_index + 1
  ```

  The updated function signature should accept `account_key` directly (it already does — `_handle_regenerate(account_key, row, scoring, model)`).

- [ ] **Step 4.2: Replace the main render body of `render_review_page()`**

  Replace everything from `# ── Model selection (top of page)` (line 48) through the end of the existing card render call (line 129) with the new two-panel body:

  ```python
  # ── Two-panel layout ──────────────────────────────────────────────────
  left_col, right_col = st.columns([1, 2])

  with left_col:
      _render_left_panel(scored_df, session)

  with right_col:
      _render_right_panel(scored_df, session)
  ```

- [ ] **Step 4.3: Add `_render_right_panel()` function**

  Add this function to `pages/review.py`:

  ```python
  def _render_right_panel(scored_df: pd.DataFrame, session: "SessionState") -> None:
      """Render the right panel: model selector, account detail card, and action bar."""

      # ── Model selector + info banner ──────────────────────────────────────
      col_model, col_info = st.columns([2, 5])
      with col_model:
          model = st.selectbox(
              "Claude Model",
              options=["claude-sonnet-4-6", "claude-opus-4-6"],
              index=0,
              key="selected_model",
          )
      with col_info:
          p1_count = (scored_df["attention_tier"] == "P1").sum() if "attention_tier" in scored_df.columns else 0
          p2_count = (scored_df["attention_tier"] == "P2").sum() if "attention_tier" in scored_df.columns else 0
          st.info(
              f"**{len(scored_df)} total accounts** across "
              f"{scored_df['region'].nunique() if 'region' in scored_df.columns else '?'} regions "
              f"| 🔴 P1: {p1_count} &nbsp; 🟡 P2: {p2_count}"
          )

      # ── Resolve selected account ──────────────────────────────────────────
      selected_key = st.session_state.get("selected_account_key")

      if not selected_key:
          st.markdown(
              "<div style='text-align:center;color:#64748b;padding:4rem 0'>"
              "Select an account from the list.</div>",
              unsafe_allow_html=True,
          )
          return

      # ── Check for completion within filtered list ─────────────────────────
      list_search = st.session_state.get("list_search", "")
      list_tier_filter = st.session_state.get("list_tier_filter", "All")
      filtered_keys = _get_filtered_account_list(scored_df, session, list_search, list_tier_filter)
      pending_in_filter = [k for k in filtered_keys if k not in session.decisions]

      if not pending_in_filter:
          st.success(
              "✅ All filtered accounts reviewed. "
              "Change filters or return to the dashboard."
          )
          if st.button("💾 Save to Master Sheets"):
              _save_to_master(session, scored_df)
          return

      # ── Load account data ─────────────────────────────────────────────────
      account_df = _find_account_row(scored_df, selected_key)
      if account_df is None:
          st.error(f"Account '{selected_key}' not found in data.")
          return

      row = account_df.iloc[0]
      scoring = _extract_scoring_from_row(row)

      # Backfill expansion scoring for old cached DataFrames
      if not scoring.get("insider_channels"):
          from src.scoring.expansion_scorer import score_expansion
          fresh_exp = score_expansion(row)
          scoring["insider_channels"] = fresh_exp.get("insider_channels", [])
          if not scoring.get("insider_product_count"):
              scoring["insider_product_count"] = fresh_exp.get("insider_product_count", 0)
          if not scoring.get("competitor_channels"):
              scoring["competitor_channels"] = fresh_exp.get("competitor_channels", [])
          if not scoring.get("whitespace_channels"):
              scoring["whitespace_channels"] = fresh_exp.get("whitespace_channels", [])

      # ── Generate or retrieve comment ──────────────────────────────────────
      comment = _get_or_generate_comment(row, scoring, selected_key, model)

      # ── Detail card (header, metrics, badges, comment text area) ─────────
      # Pass `model` so the comment label shows the model that generated this
      # specific comment (not the currently-selected dropdown value, which may
      # have changed since generation).
      comment_model = st.session_state.get("generated_comments_model", {}).get(selected_key, model)
      edited_comment = render_review_card(
          row=row,
          scoring=scoring,
          account_key=selected_key,
          generated_comment=comment,
          on_regenerate=lambda: _handle_regenerate(selected_key, row, scoring, model),
          approved_count=session.approved_count(),
          model=comment_model,
      )

      # ── Keyboard navigation (hidden buttons) ──────────────────────────────
      _render_keyboard_nav(filtered_keys, selected_key, session)

      # ── Action bar ────────────────────────────────────────────────────────
      st.markdown("---")
      action_cols = st.columns([2, 1.5, 2, 1])
      was_edited = edited_comment.strip() != comment.strip()

      with action_cols[0]:
          if st.button("✅ Approve & Next →", key=f"approve_{selected_key}", use_container_width=True, type="primary"):
              _handle_approve(session, selected_key, edited_comment.strip(), comment, was_edited, row)
              # Advance to next pending account
              next_key = _next_pending_key(filtered_keys, selected_key, session.decisions)
              if next_key:
                  st.session_state["selected_account_key"] = next_key
              st.rerun()

      with action_cols[1]:
          if st.button("⏭️ Skip", key=f"skip_{selected_key}", use_container_width=True):
              _handle_skip(session, selected_key)
              next_key = _next_pending_key(filtered_keys, selected_key, session.decisions)
              if next_key:
                  st.session_state["selected_account_key"] = next_key
              st.rerun()

      with action_cols[2]:
          approved_count = session.approved_count()
          save_label = f"💾 Save {approved_count} to Sheets" if approved_count > 0 else "💾 Save to Sheets"
          if st.button(save_label, key=f"save_{selected_key}", use_container_width=True):
              _save_to_master(session, scored_df)

      with action_cols[3]:
          st.markdown(
              "<span style='color:#475569;font-size:0.75rem'>← → to navigate</span>",
              unsafe_allow_html=True,
          )
  ```

- [ ] **Step 4.4: Add `_render_keyboard_nav()` function**

  Add this function to `pages/review.py`:

  ```python
  def _render_keyboard_nav(
      filtered_keys: list[str],
      current_key: str,
      session: "SessionState",
  ) -> None:
      """
      Inject keyboard navigation (← →) via hidden Streamlit buttons + JS.

      If the hidden-button approach is unreliable, this function does nothing
      and the hint text in the action bar remains cosmetic only.
      """
      try:
          idx = filtered_keys.index(current_key)
      except ValueError:
          return

      prev_key = filtered_keys[idx - 1] if idx > 0 else None
      next_key = filtered_keys[idx + 1] if idx < len(filtered_keys) - 1 else None

      # Hidden prev button
      if prev_key:
          if st.button("←", key="__nav_prev__", help="Previous account"):
              st.session_state["selected_account_key"] = prev_key
              st.rerun()

      # Hidden next button
      if next_key:
          if st.button("→", key="__nav_next__", help="Next account"):
              st.session_state["selected_account_key"] = next_key
              st.rerun()

      # JS listener — clicks the hidden buttons on arrow key press
      st.components.v1.html(
          """
          <script>
          (function() {
            function clickButton(label) {
              const buttons = window.parent.document.querySelectorAll('button');
              for (const btn of buttons) {
                if (btn.innerText.trim() === label) { btn.click(); break; }
              }
            }
            document.addEventListener('keydown', function(e) {
              if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
              if (e.key === 'ArrowLeft')  clickButton('←');
              if (e.key === 'ArrowRight') clickButton('→');
            }, { once: false });
          })();
          </script>
          """,
          height=0,
      )
  ```

  > **Known limitation:** The JS traverses the parent document for buttons with matching text. If multiple `←`/`→` buttons exist on the page, the first match is clicked. This is acceptable for v1. If keyboard nav causes unexpected behaviour, remove the `st.components.v1.html` call — the hidden buttons remain but are just visible small buttons without keyboard binding.

- [ ] **Step 4.5: Update `_handle_approve()` and `_handle_skip()` to NOT call `st.rerun()` themselves**

  The two-panel action bar in `_render_right_panel()` handles `st.rerun()` after calling these handlers (it needs to set `selected_account_key` first). Replace the full bodies of both functions with the versions below (only change is removal of `st.rerun()` at the end):

  ```python
  def _handle_approve(session, account_key, final_comment, original_comment, edited, row):
      regen_count = st.session_state.get(f"regen_{account_key}", 0)
      spreadsheet_id = str(row.get("spreadsheet_id", "")) or None

      st.session_state["session"] = record_decision(
          session,
          account_key=account_key,
          status="approved",
          final_comment=final_comment,
          original_comment=original_comment,
          edited=edited,
          regenerate_count=regen_count,
          spreadsheet_id=spreadsheet_id,
      )
      save_session(st.session_state["session"], DEFAULT_SESSION_DIR)
      approved_so_far = st.session_state["session"].approved_count()
      st.toast(f"✅ Approved ({approved_so_far} total) — loading next account…", icon="✅")
      # NOTE: no st.rerun() here — caller (_render_right_panel) calls st.rerun()
      # after updating selected_account_key.


  def _handle_skip(session, account_key):
      st.session_state["session"] = record_decision(
          session, account_key=account_key, status="skipped"
      )
      save_session(st.session_state["session"], DEFAULT_SESSION_DIR)
      # NOTE: no st.rerun() here — caller (_render_right_panel) calls st.rerun()
      # after updating selected_account_key.
  ```

  > Also update `_handle_approve` to use `f"regen_{account_key}"` as the regen count key (instead of the old position-based key). This matches the state key change made in Chunk 3.

- [ ] **Step 4.6: Syntax check**

  ```bash
  python -m py_compile pages/review.py
  python -m py_compile ui/components/review_card.py
  ```

  Expected: no output.

- [ ] **Step 4.7: Full integration smoke test**

  ```bash
  streamlit run app.py
  ```

  Navigate to the Review tab. Verify:

  1. Two-panel layout renders: account list on left, detail card on right.
  2. Clicking an account row in the left panel updates the right panel.
  3. NRR colours are correct (red/yellow/green).
  4. The model selector appears at the top of the right panel.
  5. Approve button records a decision, advances to next pending account, updates status chip in left panel.
  6. Skip button records a skip, advances to next pending account.
  7. Regenerate button generates a new comment (existing logic).
  8. Save to Sheets button triggers write-back (existing logic).
  9. Search filter reduces the left panel list.
  10. Tier filter (P1/P2/P3) reduces the left panel list.
  11. When all filtered accounts are reviewed, completion banner appears.
  12. No Python exceptions in the terminal.

- [ ] **Step 4.8: Commit**

  ```bash
  git add pages/review.py ui/components/review_card.py
  git commit -m "feat: two-panel review layout — account list + detail card with key-based selection"
  ```

---

## Chunk 5: Polish and edge cases

**Files:**
- Modify: `pages/review.py`, `ui/styles/custom.css`

---

- [ ] **Step 5.1: Hide the default button text for row buttons**

  The `st.button` calls in `_render_left_panel()` render visible button text above or below the HTML rows. Verify whether the CSS rule added in Step 2.4 successfully hides them. If not, try this alternative approach: replace the `st.button` + `st.markdown(row_html)` pattern with a single approach using `st.button` styled via CSS class injection:

  Add to `ui/styles/custom.css`:

  ```css
  /* Hide row-button labels; only the HTML row div is visible */
  [data-testid="stButton"] > button:has(span) {
      visibility: hidden;
      height: 0;
      padding: 0;
      margin: 0;
      min-height: 0;
  }
  ```

  > This is a best-effort fix. Streamlit's DOM structure varies by version. If styling is too unreliable, accept that each account has both an HTML row and a plain-text button — functionality is unaffected, it just looks slightly redundant. Document this as a known visual limitation.

- [ ] **Step 5.2: Verify session resume still works**

  The sidebar has a "Load Session" option. Load a previous session JSON and verify:
  - The left panel populates with accounts from the loaded session.
  - Previously approved/skipped accounts show correct status chips.
  - `selected_account_key` defaults to the first account in the filtered list (since old sessions don't have this key).
  - The right panel renders the detail card for the selected account.

  The `_initialize_session()` changes from Chunk 1 only run when a new session is created. For loaded sessions, `selected_account_key` is initialised by `_resolve_selected_key()` on first render (it falls back to the first key if `selected_account_key` is not in session state). Verify this works.

- [ ] **Step 5.3: Verify filter-change edge cases**

  1. Start a review session with default filters.
  2. Select account "X" in the left panel.
  3. Change the tier filter to P1. If "X" is a P2 account:
     - Verify the selected account changes to the first P1 in the list (not an error).
  4. Clear the search filter after typing something — verify the selected account stays selected if it's in the unfiltered list.
  5. Change the tier back to "All" — verify "X" is re-selected if it's now back in the list.

- [ ] **Step 5.4: Final commit**

  ```bash
  git add pages/review.py ui/styles/custom.css
  git commit -m "polish: two-panel review — row button CSS, session resume, filter edge cases verified"
  ```

---

## Summary

| Chunk | What it does | Files changed |
|---|---|---|
| 1 | State helpers: filter list, next-pending, key resolver | `pages/review.py` |
| 2 | Left panel: account list, search, tier filter, progress | `pages/review.py`, `ui/styles/custom.css` |
| 3 | Card refactor: key-based state, remove action buttons | `ui/components/review_card.py` |
| 4 | Two-panel wiring: layout, action bar, keyboard nav | `pages/review.py` |
| 5 | Polish: button CSS, session resume, filter edge cases | `pages/review.py`, `ui/styles/custom.css` |

No new files. No changes to scoring, ingestion, LLM, session persistence, or write-back logic.
