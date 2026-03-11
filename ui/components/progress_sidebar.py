"""
Progress sidebar component for the Streamlit app.
"""

import streamlit as st


def render_progress_sidebar() -> dict:
    """
    Render progress stats and filters in the sidebar.

    Returns:
        Dict: {"regions": [...], "tiers": [...]}
    """
    with st.sidebar:
        st.markdown("## 📊 Session Progress")

        session = st.session_state.get("session")
        if session:
            total = session.total_accounts
            reviewed = len(session.decisions)
            approved = session.approved_count()
            skipped = session.skipped_count()

            progress = session.progress_pct()
            st.progress(progress, text=f"{reviewed}/{total} reviewed")

            col1, col2, col3 = st.columns(3)
            col1.metric("✅", approved, help="Approved")
            col2.metric("⏭️", skipped, help="Skipped")
            col3.metric("⭕", total - reviewed, help="Pending")
            st.divider()
        else:
            st.info("No active session yet")
            st.divider()

        # Region filter
        st.markdown("**Region**")
        available_regions = st.session_state.get("available_regions", [])
        default_regions = available_regions if available_regions else []
        selected_regions = st.multiselect(
            "Filter by region",
            options=available_regions if available_regions else ["APAC", "EMEA", "LATAM", "NA"],
            default=default_regions,
            label_visibility="collapsed",
            key="sidebar_regions",
        )

        # Account Director filter
        st.markdown("**Account Director**")
        available_ae_names: list = []
        scored_df = st.session_state.get("scored_df")
        if scored_df is not None and "ae_name" in scored_df.columns:
            available_ae_names = sorted(
                n for n in scored_df["ae_name"].dropna().astype(str).str.strip().unique()
                if n and n.lower() not in ("nan", "n/a", "none", "")
            )
        selected_ae_names = st.multiselect(
            "Filter by Account Director",
            options=available_ae_names,
            default=[],
            label_visibility="collapsed",
            key="sidebar_ae_names",
        )

        # Tier filter
        st.markdown("**Tier**")
        selected_tiers = st.multiselect(
            "Filter by tier",
            options=["P1", "P2", "P3"],
            default=["P1", "P2"],
            label_visibility="collapsed",
            key="sidebar_tiers",
        )

        # Detect if filters differ from what the current session was started with
        active_filter = st.session_state.get("active_filter", {})
        filters_changed = (
            session is not None
            and (
                set(selected_regions) != set(active_filter.get("regions", selected_regions))
                or set(selected_tiers) != set(active_filter.get("tiers", selected_tiers))
                or set(selected_ae_names) != set(active_filter.get("ae_names", selected_ae_names))
            )
        )

        if filters_changed:
            st.warning("⚠️ Filters changed — apply to restart with new selection.")

        st.divider()

        # Apply Filters resets session without reloading data from Sheets
        if st.button(
            "✅ Apply Filters & Restart Session",
            use_container_width=True,
            type="primary" if filters_changed else "secondary",
        ):
            for key in ["session", "generated_comments"]:
                st.session_state.pop(key, None)
            st.session_state["active_filter"] = {
                "regions": selected_regions,
                "tiers": selected_tiers,
                "ae_names": selected_ae_names,
            }
            st.rerun()

        if st.button("🔄 Reload from Sheets", use_container_width=True):
            st.cache_data.clear()
            for key in ["scored_df", "master_df", "generated_comments", "session", "active_filter"]:
                st.session_state.pop(key, None)
            st.rerun()

        if session:
            if st.button("💾 Save Session", use_container_width=True):
                from src.session.persistence import save_session, DEFAULT_SESSION_DIR
                path = save_session(session, DEFAULT_SESSION_DIR)
                st.sidebar.success(f"Saved: {path.name}")

    return {"regions": selected_regions, "tiers": selected_tiers, "ae_names": selected_ae_names}
