"""
Report Page — Markdown executive summary preview and download.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd
from datetime import datetime


def render_report_page():
    scored_df: pd.DataFrame = st.session_state.get("scored_df", pd.DataFrame())
    session = st.session_state.get("session")

    st.markdown("## 📄 Global Executive Report")

    if scored_df.empty:
        st.info("Load data first (go to Account Review tab).")
        return

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 Generate Report", use_container_width=True, type="primary"):
            st.session_state["report_markdown"] = _generate_report(scored_df, session)

    st.divider()

    report_md = st.session_state.get("report_markdown")
    if not report_md:
        st.info("Click **Generate Report** to produce the executive summary.")
        return

    # Download button
    filename = f"cro_review_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    st.download_button(
        label="📥 Download Markdown Report",
        data=report_md,
        file_name=filename,
        mime="text/markdown",
        use_container_width=False,
    )

    st.divider()
    # Render preview
    st.markdown(report_md)


def _generate_report(scored_df: pd.DataFrame, session) -> str:
    """Generate and return the Markdown report string."""
    try:
        from src.report.builder import build_report_markdown
        return build_report_markdown(scored_df, session)
    except Exception as exc:
        st.error(f"Report generation failed: {exc}")
        return f"# Report Generation Error\n\n{exc}"
