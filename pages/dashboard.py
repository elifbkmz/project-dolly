"""
Dashboard Page — Risk overview and regional metrics.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st
import pandas as pd


def render_dashboard_page():
    scored_df: pd.DataFrame = st.session_state.get("scored_df", pd.DataFrame())
    if scored_df.empty:
        st.info("Load data first (go to Account Review tab).")
        return

    st.markdown("## 📊 Global Risk Dashboard")

    # ── Summary metrics ───────────────────────────────────────────────────
    p1 = (scored_df["attention_tier"] == "P1").sum() if "attention_tier" in scored_df.columns else 0
    p2 = (scored_df["attention_tier"] == "P2").sum() if "attention_tier" in scored_df.columns else 0
    p3 = (scored_df["attention_tier"] == "P3").sum() if "attention_tier" in scored_df.columns else 0
    total = len(scored_df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Accounts", total)
    c2.metric("🔴 P1 — Immediate", p1, delta=f"{p1/total*100:.0f}%" if total else "0%")
    c3.metric("🟡 P2 — Monitor", p2, delta=f"{p2/total*100:.0f}%" if total else "0%")
    c4.metric("🟢 P3 — On Track", p3, delta=f"{p3/total*100:.0f}%" if total else "0%")

    st.divider()

    # ── Regional breakdown table ──────────────────────────────────────────
    st.markdown("### Regional Breakdown")
    if "region" in scored_df.columns and "attention_tier" in scored_df.columns:
        region_stats = []
        for region in sorted(scored_df["region"].unique()):
            rdf = scored_df[scored_df["region"] == region]
            avg_nrr = _avg_nrr(rdf)
            region_stats.append({
                "Region": region,
                "Total": len(rdf),
                "P1 🔴": (rdf["attention_tier"] == "P1").sum(),
                "P2 🟡": (rdf["attention_tier"] == "P2").sum(),
                "P3 🟢": (rdf["attention_tier"] == "P3").sum(),
                "Avg NRR": avg_nrr,
            })
        st.dataframe(
            pd.DataFrame(region_stats),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # ── NRR distribution ──────────────────────────────────────────────────
    st.markdown("### NRR Distribution")
    if "nrr_tier" in scored_df.columns:
        nrr_counts = scored_df["nrr_tier"].value_counts().reindex(
            ["CRITICAL", "AT_RISK", "HEALTHY", "STRONG", "UNKNOWN"], fill_value=0
        )
        try:
            import plotly.graph_objects as go
            colors = ["#dc3545", "#ffc107", "#198754", "#0dcaf0", "#6c757d"]
            fig = go.Figure(go.Bar(
                x=nrr_counts.index.tolist(),
                y=nrr_counts.values.tolist(),
                marker_color=colors,
                text=nrr_counts.values.tolist(),
                textposition="outside",
            ))
            fig.update_layout(
                plot_bgcolor="#0f0f1e",
                paper_bgcolor="#0f0f1e",
                font={"color": "#e2e8f0"},
                yaxis_title="Number of Accounts",
                showlegend=False,
                height=320,
                margin={"t": 20, "b": 20},
            )
            st.plotly_chart(fig, use_container_width=True)
        except ImportError:
            st.bar_chart(nrr_counts)

    # ── Channel coverage chart ────────────────────────────────────────────
    st.markdown("### Channel Coverage — Insider One vs. Competitor vs. White Space")
    try:
        from ui.components.tech_stake_chart import build_tech_stake_bar_chart
        fig = build_tech_stake_bar_chart(scored_df)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
    except Exception as exc:
        st.warning(f"Channel chart unavailable: {exc}")

    # ── Top P1 accounts table ─────────────────────────────────────────────
    st.divider()
    st.markdown("### 🔴 Top P1 Accounts (Immediate Attention)")
    if "attention_tier" in scored_df.columns:
        p1_df = scored_df[scored_df["attention_tier"] == "P1"].head(15)
        display_cols = [c for c in ["account_name", "region", "ae_name", "arr", "nrr_display", "primary_signal", "composite_score"] if c in p1_df.columns]
        st.dataframe(p1_df[display_cols].rename(columns={
            "account_name": "Account", "region": "Region", "ae_name": "AE",
            "arr": "ARR", "nrr_display": "NRR", "primary_signal": "Primary Risk",
            "composite_score": "Score",
        }), use_container_width=True, hide_index=True)

    st.divider()
    _render_scoring_explainer()


def _render_scoring_explainer():
    """Render a 'How Scoring Works' reference section."""
    st.markdown("### How Scoring Works")
    st.markdown(
        "Each account receives a **composite risk score** (0–100) that determines "
        "its priority tier. The score combines three independent dimensions:"
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            "**NRR Risk (50%)**\n\n"
            "Net Revenue Retention measures whether the account is growing or shrinking.\n\n"
            "- Below 90% → CRITICAL\n"
            "- 90–99% → AT RISK\n"
            "- 100–109% → HEALTHY\n"
            "- 110%+ → STRONG"
        )
    with col2:
        st.markdown(
            "**Threading Risk (25%)**\n\n"
            "How many executive contacts you have. Fewer contacts = higher risk.\n\n"
            "- 0–1 contacts → SINGLE (high risk)\n"
            "- 2 contacts → DUAL\n"
            "- 3+ contacts → MULTI (low risk)"
        )
    with col3:
        st.markdown(
            "**Expansion Opportunity (25%)**\n\n"
            "How many product channels are uncaptured or competitor-held.\n\n"
            "- Score 60+ → HIGH opportunity\n"
            "- Score 30–59 → MEDIUM\n"
            "- Below 30 → LOW"
        )

    st.markdown("**Priority Tiers**")
    st.markdown(
        "| Tier | Rule |\n"
        "|---|---|\n"
        "| 🔴 **P1 — Immediate** | Composite score >= 65, **OR** any hard override |\n"
        "| 🟡 **P2 — Monitor** | Composite score 40–64 |\n"
        "| 🟢 **P3 — On Track** | Composite score < 40 |"
    )

    st.markdown(
        "**Hard overrides** force P1 regardless of score: "
        "NRR below 90% (CRITICAL), renewal within 90 days, or health score <= 2."
    )


def _avg_nrr(df: pd.DataFrame) -> str:
    if "nrr_raw" not in df.columns:
        return "N/A"
    vals = pd.to_numeric(df["nrr_raw"], errors="coerce").dropna()
    if vals.empty:
        return "N/A"
    return f"{vals.mean():.1f}%"
