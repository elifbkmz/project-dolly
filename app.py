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

# ── Shared data loading (cached across all pages) ────────────────────────────

@st.cache_data(ttl=1800, show_spinner="Loading regional data from Google Sheets...")
def load_master_data():
    """
    Load, normalize, join, and score all regional data from Google Sheets.
    Cached for 30 minutes (ttl=1800 seconds).
    Returns the scored master DataFrame.
    """
    from src.google.auth import get_google_credentials
    from src.google.drive_client import build_drive_service, discover_regional_files
    from src.google.sheets_client import build_sheets_service
    from src.ingestion.loader import load_all_regions
    from src.ingestion.joiner import join_all_regions
    from src.scoring.engine import run_scoring_pipeline
    from src.utils.config_loader import load_regions_config, load_column_mappings, load_scoring_weights
    from src.utils.validators import validate_master_df

    creds = get_google_credentials()
    drive_svc = build_drive_service(creds)
    sheets_svc = build_sheets_service(creds)

    regions_config = load_regions_config()
    col_mapping = load_column_mappings()

    all_region_data = load_all_regions(drive_svc, sheets_svc, regions_config, col_mapping)

    # Discover spreadsheet IDs for write-back routing
    drive_config = regions_config.get("drive", {})
    regional_ids = discover_regional_files(
        drive_svc,
        drive_config.get("shared_folder_id", ""),
        drive_config.get("file_pattern_map", {}),
    )

    master_df = join_all_regions(all_region_data, regional_ids)
    warnings = validate_master_df(master_df)
    for w in warnings:
        st.warning(w)

    scored_df = run_scoring_pipeline(master_df)
    return scored_df


# ── Page routing ─────────────────────────────────────────────────────────────

def main():
    st.title("🎯 Global Account Review Agent")
    st.caption("CRO Digital Twin — powered by Claude")

    # Load data and store in session state
    if "scored_df" not in st.session_state:
        try:
            scored_df = load_master_data()
            st.session_state["scored_df"] = scored_df
            st.session_state["available_regions"] = sorted(scored_df["region"].unique().tolist())
        except Exception as exc:
            st.error(f"Failed to load data: {exc}")
            st.info(
                "**Setup required:**\n"
                "1. Add `GOOGLE_SERVICE_ACCOUNT_JSON` to `.streamlit/secrets.toml`\n"
                "2. Add `ANTHROPIC_API_KEY` to `.streamlit/secrets.toml`\n"
                "3. Set `drive.shared_folder_id` in `config/regions.yaml`\n"
                "4. Share your Drive folder with the service account email"
            )
            st.stop()

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
