"""
Review Page — Human-in-the-loop account review loop.

Handles:
- Session initialization and resume
- One-by-one account card rendering
- Approve / Regenerate / Skip / Save to Master actions
- Auto-save after each decision
"""

import sys
from pathlib import Path
from typing import Optional
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd

from ui.components.review_card import render_review_card
from ui.components.progress_sidebar import render_progress_sidebar
from src.session.state import SessionState
from src.session.persistence import save_session, record_decision, DEFAULT_SESSION_DIR
from src.ingestion.joiner import get_account_key
from src.llm.comment_generator import (
    generate_comment_for_account, build_shared_system_prompt,
    _extract_scoring_from_row,
)
from src.llm.client import get_anthropic_client
from src.utils.config_loader import load_prompt_templates


def render_review_page():
    """Main entry point for the Review tab."""
    filters = render_progress_sidebar()

    scored_df: pd.DataFrame = st.session_state.get("scored_df", pd.DataFrame())
    if scored_df.empty:
        st.warning("No data loaded. Go to the main page and wait for data to load.")
        return

    # ── Session initialization ────────────────────────────────────────────
    if "session" not in st.session_state:
        _initialize_session(scored_df, filters)
        return  # Re-render after initialization

    session: SessionState = st.session_state["session"]

    # ── Model selection (top of page) ─────────────────────────────────────
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

    st.divider()

    # ── Check if session is complete ──────────────────────────────────────
    if session.is_complete():
        st.success(
            f"✅ Review complete! {session.approved_count()} approved, "
            f"{session.skipped_count()} skipped."
        )
        if st.button("💾 Save to Master Sheets & Generate Report"):
            _save_to_master(session, scored_df)
        return

    # ── Get current account ───────────────────────────────────────────────
    current_key = session.current_account_key()
    if not current_key:
        st.error("Session state error: no current account key.")
        return

    # Find the row for the current account
    account_df = _find_account_row(scored_df, current_key)
    if account_df is None:
        st.error(f"Account '{current_key}' not found in data. Skipping.")
        st.session_state["session"] = record_decision(
            session, current_key, "skipped"
        )
        save_session(session, DEFAULT_SESSION_DIR)
        st.rerun()
        return

    row = account_df.iloc[0]
    scoring = _extract_scoring_from_row(row)

    # Backfill insider_channels if the scored_df pre-dates this feature
    # (column won't exist in old cached DataFrames — recompute on the fly)
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
    comment = _get_or_generate_comment(row, scoring, current_key, model)

    # ── Render the Review Card ────────────────────────────────────────────
    render_review_card(
        row=row,
        scoring=scoring,
        position=session.current_index + 1,
        total=session.total_accounts,
        generated_comment=comment,
        on_approve=lambda final, edited: _handle_approve(
            session, current_key, final, comment, edited, row
        ),
        on_regenerate=lambda: _handle_regenerate(current_key, row, scoring, model),
        on_skip=lambda: _handle_skip(session, current_key),
        on_save_to_master=lambda: _save_to_master(session, scored_df),
        approved_count=session.approved_count(),
    )


# ── Action handlers ───────────────────────────────────────────────────────────

def _handle_approve(session, account_key, final_comment, original_comment, edited, row):
    regen_count = st.session_state.get(f"regen_{row.get('account_name', '')}_{session.current_index + 1}", 0)
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
    account_name = account_key.split("::", 1)[-1]
    approved_so_far = st.session_state["session"].approved_count()
    st.toast(f"✅ Approved ({approved_so_far} total) — loading next account…", icon="✅")
    st.rerun()


def _handle_skip(session, account_key):
    st.session_state["session"] = record_decision(
        session, account_key=account_key, status="skipped"
    )
    save_session(st.session_state["session"], DEFAULT_SESSION_DIR)
    st.rerun()


def _handle_regenerate(account_key, row, scoring, model):
    """Regenerate comment with higher temperature and update session state."""
    with st.spinner("Regenerating..."):
        try:
            client = get_anthropic_client()
            templates = load_prompt_templates()
            system_prompt = st.session_state.get("system_prompt") or build_shared_system_prompt(templates=templates)
            st.session_state["system_prompt"] = system_prompt

            new_comment = generate_comment_for_account(
                row=row,
                scoring=scoring,
                client=client,
                system_prompt=system_prompt,
                user_prompt_template=templates.get("user_prompt_template", ""),
                templates=templates,
                model=model,
                temperature=0.85,
            )
            comments = st.session_state.get("generated_comments", {})
            comments[account_key] = new_comment
            st.session_state["generated_comments"] = comments

            # Update the text area value
            account_name = str(row.get("account_name", ""))
            position = st.session_state["session"].current_index + 1
            st.session_state[f"comment_area_{account_name}_{position}"] = new_comment
            st.rerun()
        except Exception as exc:
            st.error(f"Regeneration failed: {exc}")


def _save_to_master(session: SessionState, scored_df: pd.DataFrame):
    """Write all approved comments back to Google Sheets."""
    approved = session.approved_decisions()
    if not approved:
        st.warning("No approved comments to save.")
        return

    from src.google.auth import get_google_credentials
    from src.google.sheets_client import build_sheets_service, write_comments_to_summary

    try:
        creds = get_google_credentials()
        sheets_svc = build_sheets_service(creds)

        # Group by spreadsheet_id
        from collections import defaultdict
        by_sheet: dict[str, dict[str, str]] = defaultdict(dict)
        for key, decision in approved.items():
            if decision.final_comment and decision.spreadsheet_id:
                account_name = key.split("::", 1)[-1]
                by_sheet[decision.spreadsheet_id][account_name] = decision.final_comment

        # Determine target write tab from config
        from src.google.sheets_client import detect_sheet_names
        from src.utils.config_loader import load_regions_config

        regions_config = load_regions_config()
        # comment_write_tab in regions.yaml controls where comments land (default: "Maps")
        comment_write_tab = regions_config.get("comment_write_tab") or \
            (regions_config.get("explicit_sheet_names") or {}).get("maps") or "Maps"

        if not by_sheet:
            st.warning("No approved comments with a valid spreadsheet ID found. "
                       "Approve at least one account before saving.")
            return

        total_written = 0
        all_debug: list = []
        for spreadsheet_id, account_map in by_sheet.items():
            tab_names = detect_sheet_names(sheets_svc, spreadsheet_id)

            # Use configured tab if present; fallback to any tab with "map" or "tech" in name
            if comment_write_tab in tab_names:
                target_tab = comment_write_tab
            else:
                target_tab = next(
                    (t for t in tab_names if "map" in t.lower() or "tech" in t.lower()),
                    tab_names[0] if tab_names else None,
                )

            if not target_tab:
                st.warning(f"Could not find write target tab in spreadsheet {spreadsheet_id}")
                continue

            result = write_comments_to_summary(
                sheets_svc, spreadsheet_id, target_tab, account_map
            )
            # Handle both old int return and new tuple return
            if isinstance(result, tuple):
                written, debug_info = result
            else:
                written, debug_info = result, {}
            total_written += written
            all_debug.append({"spreadsheet_id": spreadsheet_id, "tab": target_tab, "debug": debug_info})

        if total_written > 0:
            st.success(f"💾 Written {total_written} comment(s) to Google Sheets!")
        else:
            st.error("⚠️ 0 comments written — account name may not match the sheet exactly.")

        # Always show diagnostic details so user can see exactly where comments landed
        with st.expander("🔍 Write-back diagnostics (click to see exact cell locations)", expanded=(total_written == 0)):
            for entry in all_debug:
                d = entry["debug"]
                st.markdown(f"**Tab:** `{entry['tab']}` in spreadsheet `{entry['spreadsheet_id'][:20]}...`")
                st.markdown(f"- Header detected at **row {(d.get('header_idx') or 0) + 1}** (1-indexed in Sheets)")
                if d.get("skipped_rows"):
                    st.markdown(f"- Rows skipped before header: {d['skipped_rows']}")
                st.markdown(f"- Account column: **`{d.get('acct_col_name')}` (column index {d.get('acct_col_idx')})**")
                st.markdown(f"- CRO Comment column letter: **`{d.get('comment_col_letter')}`** "
                            f"({'newly created' if d.get('comment_col_created') else 'already existed'})")
                if d.get("cells_written"):
                    for cw in d["cells_written"]:
                        ctx_str = ""
                        if cw.get("row_context"):
                            ctx_str = " · " + ", ".join(
                                f"{k}: *{v}*" for k, v in list(cw["row_context"].items())[:4]
                            )
                        st.success(
                            f"✅ **{cw['account']}** → cell **`{cw['cell']}`** (sheet row {cw['row_offset'] + 2}){ctx_str}"
                        )
                if d.get("error"):
                    st.error(f"Error: {d['error']}")
                if d.get("sheet_sample_accounts"):
                    st.markdown(f"- First accounts found in sheet: `{d['sheet_sample_accounts']}`")
                if d.get("headers_found"):
                    st.markdown(f"- Headers in tab: `{d['headers_found']}`")
    except Exception as exc:
        st.error(f"Save to Master failed: {exc}")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _initialize_session(scored_df: pd.DataFrame, filters: dict):
    """Set up a new review session."""
    tiers = filters.get("tiers", ["P1", "P2"])
    regions = filters.get("regions", [])
    ae_names = filters.get("ae_names", [])

    df = scored_df.copy()
    if tiers and "attention_tier" in df.columns:
        df = df[df["attention_tier"].isin(tiers)]
    if regions and "region" in df.columns:
        df = df[df["region"].isin(regions)]
    if ae_names and "ae_name" in df.columns:
        df = df[df["ae_name"].isin(ae_names)]

    if df.empty:
        st.warning("No accounts match the selected filters. Adjust filters and try again.")
        return

    review_order = [get_account_key(row) for _, row in df.iterrows()]
    model = st.session_state.get("selected_model", "claude-sonnet-4-6")
    regions_loaded = sorted(scored_df["region"].unique().tolist()) if "region" in scored_df.columns else []

    session = SessionState.new(
        model=model,
        regions=regions_loaded,
        review_order=review_order,
        tiers=tiers,
    )
    st.session_state["session"] = session
    st.session_state["generated_comments"] = {}

    # Record which filters this session was started with (for change detection)
    st.session_state["active_filter"] = {"regions": regions, "tiers": tiers, "ae_names": ae_names}

    # Build system prompt once
    templates = load_prompt_templates()
    system_prompt = build_shared_system_prompt(templates=templates)
    st.session_state["system_prompt"] = system_prompt

    # Two-panel selection state
    # Note: review_order is already filtered by sidebar (region/AE/tier) at this point.
    # selected_account_key defaults to the first account in that sidebar-filtered order.
    st.session_state["selected_account_key"] = review_order[0] if review_order else None
    st.session_state["list_search"] = ""
    st.session_state["list_tier_filter"] = "All"

    st.rerun()


def _find_account_row(scored_df: pd.DataFrame, account_key: str) -> Optional[pd.DataFrame]:
    """Return the single-row DataFrame for the given account key, or None."""
    for _, row in scored_df.iterrows():
        if get_account_key(row) == account_key:
            return scored_df.loc[[_]]
    return None


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
    # Build a one-time lookup: account_key -> row, to avoid O(n²) _find_account_row calls
    key_to_row = {get_account_key(row): row for _, row in scored_df.iterrows()}

    search = list_search.strip().lower()
    keys = []
    for key in session.review_order:
        row = key_to_row.get(key)
        if row is None:
            continue
        account_name = str(row.get("account_name", "")).lower()
        tier = str(row.get("attention_tier", ""))

        if search and search not in account_name:
            continue
        if list_tier_filter != "All" and tier != list_tier_filter:
            continue
        keys.append(key)
    return keys


def _next_pending_key(
    filtered_keys: list[str],
    current_key: str,
    decisions: dict,
) -> str | None:
    """
    Return the next key after current_key in filtered_keys that has no decision yet.

    `decisions` is session.decisions — a dict keyed by account_key.
    Returns None if no pending account exists in filtered_keys.

    If current_key is not in filtered_keys (e.g. it was filtered out), returns
    the first pending key in filtered_keys, or None if all are decided.
    """
    if current_key not in filtered_keys:
        # Selected account is no longer visible — return the first pending key
        return next((k for k in filtered_keys if k not in decisions), None)

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
    decisions = session.decisions
    total = len(session.review_order)
    done = session.approved_count() + session.skipped_count()

    # ── Header
    st.markdown(
        f"**Accounts** &nbsp; "
        f"<span style='background:#334155;color:#94a3b8;font-size:0.75rem;"
        f"padding:1px 7px;border-radius:10px'>{total}</span>"
        f"&nbsp;&nbsp;"
        f"<span style='color:#4ade80;font-size:0.8rem'>{done} done</span>",
        unsafe_allow_html=True,
    )

    # ── Filters
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

    # ── Build filtered list and resolve selection
    filtered_keys = _get_filtered_account_list(scored_df, session, search, tier_filter)
    selected_key = _resolve_selected_key(
        filtered_keys, st.session_state.get("selected_account_key")
    )
    st.session_state["selected_account_key"] = selected_key

    # ── Empty state
    if not filtered_keys:
        st.markdown(
            "<div style='text-align:center;color:#64748b;padding:2rem 0'>"
            "No accounts match your filters.</div>",
            unsafe_allow_html=True,
        )
        _render_left_panel_footer(done, total)
        return

    # ── Account rows
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

            # Renewal days countdown (pd is imported at top of file)
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

            if st.button(
                account_name,
                key=f"row_btn_{key}",
                use_container_width=True,
            ):
                st.session_state["selected_account_key"] = key
                st.rerun()

            st.markdown(row_html, unsafe_allow_html=True)

    _render_left_panel_footer(done, total)


def _render_left_panel_footer(done: int, total: int) -> None:
    progress = done / total if total > 0 else 0
    st.progress(progress)
    st.caption(f"{done} / {total} reviewed")


def _get_or_generate_comment(row: pd.Series, scoring: dict, account_key: str, model: str) -> str:
    """Return cached comment or generate a new one."""
    comments = st.session_state.get("generated_comments", {})
    if account_key in comments:
        return comments[account_key]

    with st.spinner(f"Generating CRO comment for {account_key.split('::')[-1]}..."):
        try:
            client = get_anthropic_client()
            templates = load_prompt_templates()
            system_prompt = st.session_state.get("system_prompt") or build_shared_system_prompt(templates=templates)
            st.session_state["system_prompt"] = system_prompt

            comment = generate_comment_for_account(
                row=row,
                scoring=scoring,
                client=client,
                system_prompt=system_prompt,
                user_prompt_template=templates.get("user_prompt_template", ""),
                templates=templates,
                model=model,
                temperature=0.7,
            )
            comments[account_key] = comment
            st.session_state["generated_comments"] = comments
            return comment
        except Exception as exc:
            error_msg = f"[Comment generation failed: {exc}]"
            st.error(error_msg)
            return error_msg
