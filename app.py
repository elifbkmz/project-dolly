"""
Global Account Review Agent — Main Streamlit Entry Point

Run with:
    streamlit run app.py

Setup:
    1. Add Google Service Account JSON to .streamlit/secrets.toml
    2. Add ANTHROPIC_API_KEY to .streamlit/secrets.toml
    3. Set drive.shared_folder_id in config/regions.yaml
    4. pip install -r requirements.txt
"""

import sys
import gc
from pathlib import Path

# Ensure project root is on sys.path for all imports
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

st.set_page_config(
    page_title="Global Account Review Agent",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "About": "CRO Digital Twin — Global Account Review Agent v1.0",
    },
)


# ── Discover available regions (lightweight — no data loading) ────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def discover_regions():
    """Discover available regions from Drive folder structure (no sheet data loaded)."""
    from src.google.auth import get_google_credentials
    from src.google.drive_client import build_drive_service, discover_regional_files
    from src.utils.config_loader import load_regions_config

    creds = get_google_credentials()
    drive_svc = build_drive_service(creds)
    regions_config = load_regions_config()
    drive_config = regions_config.get("drive", {})

    regional_ids = discover_regional_files(
        drive_svc,
        drive_config.get("shared_folder_id", ""),
        drive_config.get("file_pattern_map", {}),
    )

    # Extract unique parent regions (e.g., "EU" from "EU/Deniz Ficici")
    parent_regions = sorted(set(
        k.split("/")[0] if "/" in k else k
        for k in regional_ids.keys()
    ))

    return regional_ids, parent_regions


# ── Load data for selected regions only ───────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner="Loading account data...")
def load_data_for_regions(selected_regions: tuple):
    """Load, normalize, join, and score data for the selected regions only."""
    from src.google.auth import get_google_credentials
    from src.google.drive_client import build_drive_service, discover_regional_files
    from src.google.sheets_client import build_sheets_service
    from src.ingestion.loader import load_region_from_sheets
    from src.ingestion.joiner import join_all_regions
    from src.scoring.engine import run_scoring_pipeline
    from src.utils.config_loader import load_regions_config, load_column_mappings
    from src.utils.validators import validate_master_df

    creds = get_google_credentials()
    drive_svc = build_drive_service(creds)
    sheets_svc = build_sheets_service(creds)
    regions_config = load_regions_config()
    col_mapping = load_column_mappings()

    drive_config = regions_config.get("drive", {})
    all_regional_ids = discover_regional_files(
        drive_svc,
        drive_config.get("shared_folder_id", ""),
        drive_config.get("file_pattern_map", {}),
    )

    # Filter to only selected regions
    filtered_ids = {
        k: v for k, v in all_regional_ids.items()
        if any(
            k == region or k.startswith(region + "/")
            for region in selected_regions
        )
    }

    all_region_data = {}
    for region, spreadsheet_id in filtered_ids.items():
        try:
            all_region_data[region] = load_region_from_sheets(
                sheets_svc, spreadsheet_id, region, regions_config, col_mapping
            )
        except Exception:
            all_region_data[region] = {}

    master_df = join_all_regions(all_region_data, filtered_ids)
    del all_region_data
    gc.collect()

    warnings = validate_master_df(master_df)
    scored_df = run_scoring_pipeline(master_df)
    del master_df
    gc.collect()

    return scored_df, warnings


# ── Page routing ─────────────────────────────────────────────────────────────

def main():
    st.title("🎯 Global Account Review Agent")
    st.caption("CRO Digital Twin — powered by Claude")

    # Step 1: Discover regions (fast, no data loading)
    try:
        regional_ids, parent_regions = discover_regions()
    except Exception as exc:
        st.error(f"Failed to connect to Google Drive: {exc}")
        st.info(
            "**Setup required:**\n"
            "1. Add `GOOGLE_SERVICE_ACCOUNT_JSON` to `.streamlit/secrets.toml`\n"
            "2. Add `ANTHROPIC_API_KEY` to `.streamlit/secrets.toml`\n"
            "3. Set `drive.shared_folder_id` in `config/regions.yaml`\n"
            "4. Share your Drive folder with the service account email"
        )
        st.stop()

    # Step 2: Let user pick regions to load
    if "scored_df" not in st.session_state:
        st.subheader("Select regions to load")
        st.caption(f"{len(regional_ids)} spreadsheets found across {len(parent_regions)} regions")

        selected = st.multiselect(
            "Regions",
            parent_regions,
            default=parent_regions,
            key="region_selector",
        )

        if not selected:
            st.warning("Select at least one region.")
            st.stop()

        if st.button("Load Selected Regions", type="primary"):
            with st.spinner(f"Loading {len(selected)} region(s)..."):
                scored_df, warnings = load_data_for_regions(tuple(selected))
                for w in warnings:
                    st.warning(w)
                st.session_state["scored_df"] = scored_df
                st.session_state["available_regions"] = sorted(
                    scored_df["region"].unique().tolist()
                ) if "region" in scored_df.columns else selected
                st.rerun()
        st.stop()

    # ── Data loaded — show main app ──────────────────────────────────────

    scored_df = st.session_state["scored_df"]

    # Reload button in sidebar
    if st.sidebar.button("Reload / Change Regions"):
        for key in ["scored_df", "available_regions", "session", "welcome_dismissed"]:
            st.session_state.pop(key, None)
        st.cache_data.clear()
        st.rerun()

    # Welcome banner
    if not st.session_state.get("welcome_dismissed"):
        total = len(scored_df)
        p1 = int((scored_df["attention_tier"] == "P1").sum()) if "attention_tier" in scored_df.columns else 0
        p2 = int((scored_df["attention_tier"] == "P2").sum()) if "attention_tier" in scored_df.columns else 0
        st.info(
            f"**Welcome to the Global Account Review Agent**\n\n"
            f"Your portfolio has **{total} accounts** scored and prioritized. "
            f"**{p1} critical** and **{p2} at-risk** need your attention. "
            f"Start with the **Account Review** tab to review and approve CRO comments."
        )
        if st.button("Got it", key="dismiss_welcome"):
            st.session_state["welcome_dismissed"] = True
            st.rerun()

    # Tab navigation
    tab1, tab2, tab3 = st.tabs(["🔍 Account Review", "📊 Risk Dashboard", "📄 Report"])

    with tab1:
        from pages.review import render_review_page
        render_review_page()

    with tab2:
        from pages.dashboard import render_dashboard_page
        render_dashboard_page()

    with tab3:
        from pages.report import render_report_page
        render_report_page()


if __name__ == "__main__":
    main()
