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
from src.session.state import SessionState, AccountDecision
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


# ── Step indicator ─────────────────────────────────────────────────────────────


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


# ── Step 1: Portfolio Summary ─────────────────────────────────────────────────


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
        st.success(f"Portfolio comment for {selected_region} approved.")
        st.text_area("Approved Comment", value=existing_decision.final_comment, disabled=True, height=120)

        # Save to Overview tab button
        save_col, _ = st.columns([2, 3])
        with save_col:
            if st.button("💾 Save to Overview Tab", key=f"save_portfolio_{selected_region}", type="primary"):
                _save_portfolio_to_sheet(session, scored_df, selected_region)
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
            if st.button("Approve Portfolio Comment", type="primary", key="approve_portfolio"):
                from datetime import datetime, timezone
                decision = AccountDecision(
                    account_key=region_key,
                    status="approved",
                    final_comment=edited_comment.strip(),
                    original_comment=portfolio_comment,
                    edited=edited_comment.strip() != portfolio_comment.strip(),
                    comment_type="portfolio",
                )
                session.portfolio_decisions[region_key] = decision
                session.last_saved_at = datetime.now(timezone.utc).isoformat()
                save_session(session, DEFAULT_SESSION_DIR)
                st.session_state["session"] = session
                st.toast(f"Portfolio comment for {selected_region} approved!")
                st.rerun()

        with act2:
            if st.button("Regenerate", key="regen_portfolio"):
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
            from datetime import datetime, timezone
            session.review_step = 2
            session.last_saved_at = datetime.now(timezone.utc).isoformat()
            save_session(session, DEFAULT_SESSION_DIR)
            st.session_state["session"] = session
            st.rerun()

    with nav1:
        if not all_regions_done:
            pending = [r for r in regions if f"PORTFOLIO::{r}" not in session.portfolio_decisions
                       or session.portfolio_decisions[f"PORTFOLIO::{r}"].status != "approved"]
            st.caption(f"Pending regions: {', '.join(pending)}")


# ── Step 3: Tech Stack Reviews ────────────────────────────────────────────────


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
        gap_col1, gap_col2 = st.columns(2)
        with gap_col1:
            st.markdown("**Competitor-held Channels:**")
            for g in gaps["competitor_gaps"]:
                st.markdown(f"- {g}")
            if not gaps["competitor_gaps"]:
                st.markdown("*None*")
        with gap_col2:
            st.markdown("**Whitespace (uncaptured):**")
            for g in gaps["whitespace_gaps"]:
                st.markdown(f"- {g}")
            if not gaps["whitespace_gaps"]:
                st.markdown("*None*")

        st.markdown("---")

        # Comment generation
        existing = session.tech_stake_decisions.get(selected_key)
        if existing and existing.status == "approved":
            st.success("Comment approved.")
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
                if st.button("Approve & Next", key=f"ts_approve_{selected_key}", type="primary"):
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
                if st.button("Skip", key=f"ts_skip_{selected_key}"):
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
                if st.button("Regen", key=f"ts_regen_{selected_key}"):
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


# ── Portfolio save ────────────────────────────────────────────────────────────


def _save_portfolio_to_sheet(session: SessionState, scored_df: pd.DataFrame, region: str):
    """Write the approved portfolio comment as a threaded comment on the Overview tab."""
    from src.google.auth import get_google_credentials
    from src.google.drive_client import build_drive_service, add_threaded_comment
    from src.google.sheets_client import build_sheets_service, detect_sheet_names

    region_key = f"PORTFOLIO::{region}"
    decision = session.portfolio_decisions.get(region_key)
    if not decision or not decision.final_comment:
        st.warning("No approved portfolio comment to save.")
        return

    try:
        creds = get_google_credentials()
        drive_svc = build_drive_service(creds)
        sheets_svc = build_sheets_service(creds)

        # Find the spreadsheet ID for this region
        region_rows = scored_df[scored_df["region"] == region] if "region" in scored_df.columns else scored_df
        if region_rows.empty:
            st.error(f"No data found for region {region}.")
            return

        sid = str(region_rows.iloc[0].get("spreadsheet_id", ""))
        if not sid:
            st.error("No spreadsheet ID found for this region.")
            return

        # Find the Overview tab name and its gid
        tab_names = detect_sheet_names(sheets_svc, sid)
        target = next((t for t in tab_names if "overview" in t.lower()), "Overview")

        if target not in tab_names:
            st.error(f"Tab '{target}' not found in spreadsheet. Available: {tab_names}")
            return

        # Get sheet gid from spreadsheet properties
        sheet_metadata = sheets_svc.spreadsheets().get(
            spreadsheetId=sid, fields="sheets.properties"
        ).execute()
        sheet_gid = 0
        for sheet in sheet_metadata.get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("title") == target:
                sheet_gid = props.get("sheetId", 0)
                break

        # Add comment anchored to the Overview sheet tab
        result = add_threaded_comment(
            drive_service=drive_svc,
            file_id=sid,
            comment_text=decision.final_comment,
            sheet_gid=sheet_gid,
        )

        comment_id = result.get("id", "unknown")
        st.success(
            f"Portfolio comment saved to '{target}' tab — comment #{comment_id}"
        )

        with st.expander("Comment details"):
            st.json(result)

    except Exception as exc:
        st.error(f"Save failed: {exc}")


# ── Multi-tab save ────────────────────────────────────────────────────────────


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

    label = f"Save All ({portfolio_count} portfolio + {account_count} account + {tech_count} tech stake)"
    if st.button(label, key="save_all_tabs", type="primary"):
        _save_all_tabs(session, scored_df)


def _save_all_tabs(session: SessionState, scored_df: pd.DataFrame):
    """Write approved comments to their respective tabs (Overview, Maps, Tech Stack)."""
    from src.google.auth import get_google_credentials
    from src.google.drive_client import build_drive_service, add_threaded_comment, add_cell_comment
    from src.google.sheets_client import (
        build_sheets_service, detect_sheet_names, find_account_cell,
    )
    from src.utils.config_loader import load_regions_config
    from collections import defaultdict

    try:
        creds = get_google_credentials()
        sheets_svc = build_sheets_service(creds)
        drive_svc = build_drive_service(creds)
        regions_config = load_regions_config()
        write_tabs = regions_config.get("comment_write_tabs", {})
        portfolio_tab = write_tabs.get("portfolio", "Overview")
        accounts_tab = write_tabs.get("accounts",
                                       regions_config.get("comment_write_tab", "Maps"))
        tech_stake_tab = write_tabs.get("tech_stake", "Current Tech Stake Information")

        total_written = 0
        all_debug = []
        all_approved = session.all_approved_decisions()

        # ── 1. Portfolio comments → Overview tab (threaded comment via Drive API)
        portfolio_decisions = {k: d for k, d in all_approved.items() if d.comment_type == "portfolio"}
        for key, decision in portfolio_decisions.items():
            if not decision.final_comment:
                continue
            region = key.replace("PORTFOLIO::", "")
            region_rows = scored_df[scored_df["region"] == region] if "region" in scored_df.columns else scored_df
            if not region_rows.empty:
                sid = str(region_rows.iloc[0].get("spreadsheet_id", ""))
                if sid:
                    tab_names = detect_sheet_names(sheets_svc, sid)
                    target = next((t for t in tab_names if "overview" in t.lower()), portfolio_tab)
                    # Get sheet gid
                    sheet_metadata = sheets_svc.spreadsheets().get(
                        spreadsheetId=sid, fields="sheets.properties"
                    ).execute()
                    sheet_gid = 0
                    for sheet in sheet_metadata.get("sheets", []):
                        props = sheet.get("properties", {})
                        if props.get("title") == target:
                            sheet_gid = props.get("sheetId", 0)
                            break
                    try:
                        result = add_threaded_comment(drive_svc, sid, decision.final_comment, sheet_gid)
                        decision.drive_comment_id = result.get("id")
                        all_debug.append({"type": "portfolio", "region": region, "comment_id": result.get("id")})
                        total_written += 1
                    except Exception as exc:
                        all_debug.append({"type": "portfolio", "region": region, "error": str(exc)})

        # ── 2. Account comments → Maps tab (cell-anchored comments via Drive API)
        account_decisions = {k: d for k, d in all_approved.items() if d.comment_type == "account"}
        by_sheet_accounts = defaultdict(dict)
        account_decision_lookup: dict = {}  # (sid, account_name) → decision
        for key, decision in account_decisions.items():
            if decision.final_comment and decision.spreadsheet_id:
                parts = key.split("::")
                account_name = parts[1] if len(parts) >= 2 else key
                by_sheet_accounts[decision.spreadsheet_id][account_name] = decision.final_comment
                account_decision_lookup[(decision.spreadsheet_id, account_name)] = decision

        for sid, account_map in by_sheet_accounts.items():
            tab_names = detect_sheet_names(sheets_svc, sid)
            target = accounts_tab if accounts_tab in tab_names else next(
                (t for t in tab_names if "map" in t.lower()), tab_names[0] if tab_names else None
            )
            if not target:
                continue
            # Get sheet gid for anchor
            sheet_metadata = sheets_svc.spreadsheets().get(
                spreadsheetId=sid, fields="sheets.properties"
            ).execute()
            sheet_gid = 0
            for sheet in sheet_metadata.get("sheets", []):
                props = sheet.get("properties", {})
                if props.get("title") == target:
                    sheet_gid = props.get("sheetId", 0)
                    break

            for account_name, comment_text in account_map.items():
                cell_info = find_account_cell(
                    sheets_svc, sid, target, account_name,
                    target_col="account_name", fallback_col="account_name",
                )
                if not cell_info["found"]:
                    all_debug.append({
                        "type": "account", "account": account_name,
                        "error": cell_info["debug"],
                    })
                    continue
                try:
                    result = add_cell_comment(
                        drive_svc, sid, comment_text,
                        sheet_gid=sheet_gid,
                        cell_ref=cell_info["cell_ref"],
                        quoted_text=cell_info["cell_text"],
                    )
                    all_debug.append({
                        "type": "account", "account": account_name,
                        "cell": cell_info["cell_ref"],
                        "comment_id": result.get("id"),
                    })
                    total_written += 1
                    acct_decision = account_decision_lookup.get((sid, account_name))
                    if acct_decision:
                        acct_decision.drive_comment_id = result.get("id")
                except Exception as exc:
                    all_debug.append({
                        "type": "account", "account": account_name,
                        "error": str(exc),
                    })

        # ── 3. Tech stake comments → Tech Stack tab (cell-anchored comments via Drive API)
        tech_decisions = {k: d for k, d in all_approved.items() if d.comment_type == "tech_stake"}
        by_sheet_tech = defaultdict(dict)
        tech_decision_lookup: dict = {}  # (sid, account_name) → decision
        for key, decision in tech_decisions.items():
            if decision.final_comment and decision.spreadsheet_id:
                parts = key.split("::")
                account_name = parts[1] if len(parts) >= 2 else key
                by_sheet_tech[decision.spreadsheet_id][account_name] = decision.final_comment
                tech_decision_lookup[(decision.spreadsheet_id, account_name)] = decision

        for sid, account_map in by_sheet_tech.items():
            tab_names = detect_sheet_names(sheets_svc, sid)
            target = tech_stake_tab if tech_stake_tab in tab_names else next(
                (t for t in tab_names if "tech" in t.lower() and "stake" in t.lower()),
                next((t for t in tab_names if "tech" in t.lower()), None)
            )
            if not target:
                continue
            # Get sheet gid for anchor
            sheet_metadata = sheets_svc.spreadsheets().get(
                spreadsheetId=sid, fields="sheets.properties"
            ).execute()
            sheet_gid = 0
            for sheet in sheet_metadata.get("sheets", []):
                props = sheet.get("properties", {})
                if props.get("title") == target:
                    sheet_gid = props.get("sheetId", 0)
                    break

            for account_name, comment_text in account_map.items():
                cell_info = find_account_cell(
                    sheets_svc, sid, target, account_name,
                    target_col="account_name", fallback_col="account_name",
                )
                if not cell_info["found"]:
                    all_debug.append({
                        "type": "tech_stake", "account": account_name,
                        "error": cell_info["debug"],
                    })
                    continue
                try:
                    result = add_cell_comment(
                        drive_svc, sid, comment_text,
                        sheet_gid=sheet_gid,
                        cell_ref=cell_info["cell_ref"],
                        quoted_text=cell_info["cell_text"],
                    )
                    all_debug.append({
                        "type": "tech_stake", "account": account_name,
                        "cell": cell_info["cell_ref"],
                        "comment_id": result.get("id"),
                    })
                    total_written += 1
                    tech_decision = tech_decision_lookup.get((sid, account_name))
                    if tech_decision:
                        tech_decision.drive_comment_id = result.get("id")
                except Exception as exc:
                    all_debug.append({
                        "type": "tech_stake", "account": account_name,
                        "error": str(exc),
                    })

        # Results
        if total_written > 0:
            st.success(f"Written {total_written} comment(s) across all tabs!")
        else:
            st.error("0 comments written — check diagnostics below.")

        with st.expander("Multi-tab write-back diagnostics", expanded=(total_written == 0)):
            for entry in all_debug:
                st.json(entry)

    except Exception as exc:
        st.error(f"Multi-tab save failed: {exc}")


# ── Action handlers ───────────────────────────────────────────────────────────

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
    # NOTE: no st.rerun() here — caller handles it after updating selected_account_key


def _handle_skip(session, account_key):
    st.session_state["session"] = record_decision(
        session, account_key=account_key, status="skipped"
    )
    save_session(st.session_state["session"], DEFAULT_SESSION_DIR)
    # NOTE: no st.rerun() here — caller handles it after updating selected_account_key


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
            st.session_state[f"comment_area_{account_key}"] = new_comment
            st.rerun()
        except Exception as exc:
            st.error(f"Regeneration failed: {exc}")


def _save_to_master(session: SessionState, scored_df: pd.DataFrame):
    """Write all approved comments back to Google Sheets as cell comments."""
    approved = session.approved_decisions()
    if not approved:
        st.warning("No approved comments to save.")
        return

    from src.google.auth import get_google_credentials
    from src.google.drive_client import build_drive_service, add_cell_comment
    from src.google.sheets_client import (
        build_sheets_service, detect_sheet_names, find_account_cell,
    )

    try:
        creds = get_google_credentials()
        sheets_svc = build_sheets_service(creds)
        drive_svc = build_drive_service(creds)

        # Group by spreadsheet_id
        from collections import defaultdict
        by_sheet: dict[str, dict[str, str]] = defaultdict(dict)
        for key, decision in approved.items():
            if decision.final_comment and decision.spreadsheet_id:
                parts = key.split("::")
                account_name = parts[1] if len(parts) >= 2 else key
                by_sheet[decision.spreadsheet_id][account_name] = decision.final_comment

        from src.utils.config_loader import load_regions_config
        regions_config = load_regions_config()
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

            # Get sheet gid
            sheet_metadata = sheets_svc.spreadsheets().get(
                spreadsheetId=spreadsheet_id, fields="sheets.properties"
            ).execute()
            sheet_gid = 0
            for sheet in sheet_metadata.get("sheets", []):
                props = sheet.get("properties", {})
                if props.get("title") == target_tab:
                    sheet_gid = props.get("sheetId", 0)
                    break

            for account_name, comment_text in account_map.items():
                cell_info = find_account_cell(
                    sheets_svc, spreadsheet_id, target_tab, account_name,
                    target_col="next_steps", fallback_col="account_name",
                )
                if not cell_info["found"]:
                    all_debug.append({
                        "account": account_name, "error": cell_info["debug"],
                    })
                    continue
                try:
                    result = add_cell_comment(
                        drive_svc, spreadsheet_id, comment_text,
                        sheet_gid=sheet_gid,
                        cell_ref=cell_info["cell_ref"],
                        quoted_text=cell_info["cell_text"],
                    )
                    all_debug.append({
                        "account": account_name,
                        "cell": cell_info["cell_ref"],
                        "comment_id": result.get("id"),
                    })
                    total_written += 1
                except Exception as exc:
                    all_debug.append({
                        "account": account_name, "error": str(exc),
                    })

        if total_written > 0:
            st.success(f"Written {total_written} comment(s) to Google Sheets!")
        else:
            st.error("0 comments written — check diagnostics below.")

        with st.expander("Write-back diagnostics", expanded=(total_written == 0)):
            for entry in all_debug:
                st.json(entry)

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

    # Deduplicate: same account can appear in multiple rows if data has overlaps
    seen = set()
    review_order = []
    for _, row in df.iterrows():
        k = get_account_key(row)
        if k not in seen:
            seen.add(k)
            review_order.append(k)

    # Sort review_order: MRR descending (highest MRR first), then composite score as tiebreaker
    key_to_row = {get_account_key(row): row for _, row in df.iterrows()}

    def _sort_key(account_key):
        row = key_to_row.get(account_key)
        if row is None:
            return (0,)  # Unknown accounts last (lowest MRR)
        try:
            arr = float(str(row.get("arr", 0)).replace("$", "").replace(",", "").strip())
        except (ValueError, TypeError):
            arr = 0
        composite = float(row.get("composite_score", 0) or 0)
        return (-arr, -composite)  # MRR descending, then composite descending

    review_order.sort(key=_sort_key)

    model = st.session_state.get("selected_model", "claude-sonnet-4-6")
    regions_loaded = sorted(scored_df["region"].unique().tolist()) if "region" in scored_df.columns else []

    session = SessionState.new(
        model=model,
        regions=regions_loaded,
        review_order=review_order,
        tiers=tiers,
    )
    # Initialize tech stake order for Step 3
    from src.llm.tech_stake_comment import filter_accounts_with_gaps
    gap_df = filter_accounts_with_gaps(scored_df, min_arr=5000)
    session.tech_stake_order = [get_account_key(row) for _, row in gap_df.iterrows()]

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
    show_low_mrr: bool = False,
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
        if not show_low_mrr and row.get("skip_auto_comment", False):
            continue
        keys.append(key)
    return keys


def _next_pending_key(
    filtered_keys: list[str],
    current_key: str,
    decisions: dict,
) -> Optional[str]:
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
    current_selected: Optional[str],
) -> Optional[str]:
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
    show_low_mrr = st.checkbox(
        "Show low-MRR accounts",
        value=st.session_state.get("show_low_mrr", False),
        key="show_low_mrr",
    )

    # ── Build filtered list and resolve selection
    filtered_keys = _get_filtered_account_list(scored_df, session, search, tier_filter, show_low_mrr)
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
        for idx, key in enumerate(filtered_keys):
            row_df = _find_account_row(scored_df, key)
            if row_df is None:
                continue
            row = row_df.iloc[0]

            account_name = str(row.get("account_name", key)).strip()
            ae_name = str(row.get("ae_name", "") or "").strip()
            ae_name = ae_name if ae_name.lower() not in ("nan", "n/a", "none", "") else ""
            tier = str(row.get("attention_tier", "P3"))
            nrr_display = str(row.get("nrr_display") or row.get("nrr") or "N/A")
            renewal_date = str(row.get("renewal_date", "N/A") or "N/A").strip()
            region = str(row.get("region", "")).strip()
            primary_signal = str(row.get("primary_signal", "")).strip()
            primary_signal = primary_signal if primary_signal.lower() not in ("nan", "n/a", "none", "") else ""

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
              <div style="display:flex;gap:10px;margin-top:3px;flex-wrap:wrap">
                {f'<span style="color:#6ea8fe;font-size:0.72rem">AE: {ae_name}</span>' if ae_name else ''}
                <span style="color:{nrr_colour};font-size:0.75rem">NRR {nrr_display}</span>
                <span style="color:#94a3b8;font-size:0.75rem">{renewal_display}</span>
                <span style="color:#94a3b8;font-size:0.75rem">{region}</span>
              </div>
              {'<div style="font-size:0.7rem;color:#94a3b8;font-style:italic;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px">' + primary_signal + '</div>' if primary_signal else ''}
            </div>
            """

            if st.button(
                account_name,
                key=f"row_btn_{idx}",
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


def _render_right_panel(scored_df: pd.DataFrame, session: "SessionState") -> None:
    """Render the right panel: model selector, account detail card, and action bar."""

    # ── Model selector + info banner
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

    # ── Resolve selected account
    selected_key = st.session_state.get("selected_account_key")

    if not selected_key:
        st.markdown(
            "<div style='text-align:center;color:#64748b;padding:4rem 0'>"
            "Select an account from the list.</div>",
            unsafe_allow_html=True,
        )
        return

    # ── Check for completion within filtered list
    list_search = st.session_state.get("list_search", "")
    list_tier_filter = st.session_state.get("list_tier_filter", "All")
    filtered_keys = _get_filtered_account_list(scored_df, session, list_search, list_tier_filter)
    pending_in_filter = [k for k in filtered_keys if k not in session.decisions]

    if not pending_in_filter and selected_key in session.decisions:
        st.success("All account reviews complete!")
        col_save, col_next = st.columns(2)
        with col_save:
            if st.button("Save Account Comments to Maps"):
                _save_to_master(session, scored_df)
        with col_next:
            if st.button("Next Step → Tech Stack Reviews", type="primary"):
                session.review_step = 3
                save_session(session, DEFAULT_SESSION_DIR)
                st.session_state["session"] = session
                st.rerun()
        return

    # ── Load account data
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

    # ── Generate or retrieve comment
    comment = _get_or_generate_comment(row, scoring, selected_key, model)

    # ── Detail card (header, metrics, badges, comment text area)
    edited_comment = render_review_card(
        row=row,
        scoring=scoring,
        account_key=selected_key,
        generated_comment=comment,
        on_regenerate=lambda: _handle_regenerate(selected_key, row, scoring, model),
        approved_count=session.approved_count(),
        model=model,
    )

    # ── Keyboard navigation (hidden buttons)
    _render_keyboard_nav(filtered_keys, selected_key)

    # ── Action bar
    st.markdown("---")
    action_cols = st.columns([2, 1.5, 2, 1])
    was_edited = edited_comment.strip() != comment.strip()

    with action_cols[0]:
        if st.button("✅ Approve & Next →", key=f"approve_{selected_key}", use_container_width=True, type="primary"):
            _handle_approve(session, selected_key, edited_comment.strip(), comment, was_edited, row)
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


def _render_keyboard_nav(
    filtered_keys: list[str],
    current_key: str,
) -> None:
    """Inject keyboard navigation (← →) via hidden Streamlit buttons + JS."""
    try:
        idx = filtered_keys.index(current_key)
    except ValueError:
        return

    prev_key = filtered_keys[idx - 1] if idx > 0 else None
    next_key = filtered_keys[idx + 1] if idx < len(filtered_keys) - 1 else None

    if prev_key:
        if st.button("←", key="__nav_prev__", help="Previous account"):
            st.session_state["selected_account_key"] = prev_key
            st.rerun()

    if next_key:
        if st.button("→", key="__nav_next__", help="Next account"):
            st.session_state["selected_account_key"] = next_key
            st.rerun()

    import streamlit.components.v1
    streamlit.components.v1.html(
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


def _get_or_generate_comment(row: pd.Series, scoring: dict, account_key: str, model: str) -> str:
    """Return cached comment or generate a new one."""
    comments = st.session_state.get("generated_comments", {})
    if account_key in comments:
        return comments[account_key]

    with st.spinner(f"Generating CRO comment for {account_key.split('::')[1] if '::' in account_key else account_key}..."):
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
