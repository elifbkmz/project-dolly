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

    st.rerun()


def _find_account_row(scored_df: pd.DataFrame, account_key: str) -> Optional[pd.DataFrame]:
    """Return the single-row DataFrame for the given account key, or None."""
    for _, row in scored_df.iterrows():
        if get_account_key(row) == account_key:
            return scored_df.loc[[_]]
    return None


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
