"""
Review Card component — the centerpiece of the demo.

Renders one account card with:
- Header: name, region, attention tier badge, position counter
- Financial metrics: ARR, NRR, Renewal, Health, Stage
- Threading + Expansion badges
- Tech Stake breakdown (expandable)
- Risk flags (expandable)
- Editable CRO comment text area
- Buttons: Approve, Regenerate, Skip, Save to Master
"""

import streamlit as st
import pandas as pd
from pathlib import Path

from ui.components.risk_badges import (
    attention_tier_badge, nrr_badge, threading_badge,
    expansion_badge, build_risk_flags,
)
from ui.components.tech_stake_chart import render_channel_chips


def load_css():
    """Inject custom CSS into the Streamlit app (call once per session)."""
    css_path = Path(__file__).parent.parent / "styles" / "custom.css"
    if css_path.exists() and not st.session_state.get("_css_loaded"):
        st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)
        st.session_state["_css_loaded"] = True


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
    """
    Render the full account Review Card.

    Args:
        row: Account row from scored DataFrame.
        scoring: Scoring dict for this account.
        position: Current position (1-indexed).
        total: Total accounts in this review session.
        generated_comment: AI-generated comment text.
        on_approve:         Callable(final_comment: str, was_edited: bool)
        on_regenerate:      Callable()
        on_skip:            Callable()
        on_save_to_master:  Callable()
        approved_count:     Number of approved comments not yet saved to Sheets.
    """
    load_css()

    account_name = str(row.get("account_name", "Unknown")).strip()
    region = str(row.get("region", "")).strip()
    ae_name = str(row.get("ae_name", "N/A")).strip() or "N/A"
    territory = str(row.get("territory", "")).strip()
    attention_tier = scoring.get("attention_tier", "P2")
    nrr_display = scoring.get("nrr_display", "N/A")
    nrr_tier = scoring.get("nrr_tier", "UNKNOWN")

    # ── Header ────────────────────────────────────────────────────────────
    tier_html = attention_tier_badge(attention_tier)
    region_meta = f"{region} &nbsp;·&nbsp; Account {position} of {total}"
    st.markdown(
        f"""
        <div style="display:flex; justify-content:space-between; align-items:center;
                    padding-bottom:0.75rem; margin-bottom:0.75rem;
                    border-bottom:1px solid #2d2d4a;">
            <div>{tier_html}
                 <span style="margin-left:0.75rem; color:#9ca3af; font-size:0.85rem;">
                     {region_meta}
                 </span>
            </div>
        </div>
        <h2 style="margin:0 0 0.15rem 0; font-size:1.35rem; color:#e2e8f0;">{account_name}</h2>
        <div style="color:#9ca3af; font-size:0.85rem; margin-bottom:0.75rem;">
            AE: <strong style="color:#e2e8f0;">{ae_name}</strong>
            {"&nbsp;·&nbsp; " + territory if territory else ""}
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Financial metrics ─────────────────────────────────────────────────
    arr_display = _fmt_currency(row.get("arr"))
    renewal_date = str(row.get("renewal_date", "N/A")).strip() or "N/A"
    health_raw = str(row.get("health_score", "")).strip()
    health_display = health_raw if health_raw and health_raw not in ("nan", "") else "N/A"
    deal_stage = str(row.get("deal_stage", "N/A")).strip() or "N/A"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("💰 ARR", arr_display)
    m2.metric("📈 NRR", f"{nrr_display}")
    m3.metric("📅 Renewal", renewal_date)
    m4.metric("💊 Health", health_display)
    st.caption(f"**Stage:** {deal_stage} &nbsp;|&nbsp; **NRR Tier:** {nrr_tier}")

    # ── Status badges ─────────────────────────────────────────────────────
    badges_html = (
        threading_badge(scoring.get("threading_tier", "UNKNOWN"), scoring.get("contact_count"))
        + "&nbsp;&nbsp;"
        + expansion_badge(scoring.get("expansion_tier", "LOW"), float(scoring.get("expansion_score", 0) or 0))
    )
    st.markdown(f"<div style='margin:0.5rem 0;'>{badges_html}</div>", unsafe_allow_html=True)

    # ── Tech Stake breakdown ──────────────────────────────────────────────
    with st.expander("📦 Tech Stake Breakdown", expanded=True):
        st.markdown(render_channel_chips(scoring), unsafe_allow_html=True)

    # ── Risk flags ────────────────────────────────────────────────────────
    with st.expander("⚠️ Risk & Opportunity Profile", expanded=True):
        st.markdown(build_risk_flags(scoring), unsafe_allow_html=True)

    # ── CRO Comment ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**🤖 CRO Suggested Comment** *(claude-sonnet-4-6)*")

    # State keys scoped to this account
    comment_area_key = f"comment_area_{account_name}_{position}"
    regen_count_key = f"regen_{account_name}_{position}"

    # Pre-populate the text area with the generated comment on first render
    if comment_area_key not in st.session_state:
        st.session_state[comment_area_key] = generated_comment

    edited_comment = st.text_area(
        "Edit before approving:",
        value=st.session_state[comment_area_key],
        height=140,
        key=comment_area_key,
        help="The AI-generated comment. Modify freely before approving.",
    )
    was_edited = edited_comment.strip() != generated_comment.strip()

    # ── Pending save banner ───────────────────────────────────────────────
    if approved_count > 0:
        st.info(
            f"💾 **{approved_count} approved comment(s) not yet written to Google Sheets.** "
            f"Click **Save {approved_count} to Sheets** below anytime, or continue reviewing first.",
            icon="💡",
        )

    # ── Action buttons ────────────────────────────────────────────────────
    b1, b2, b3, b4 = st.columns([2.5, 2, 1.5, 2.5])

    with b1:
        if st.button("✅ Approve & Next →", key=f"approve_{position}", use_container_width=True, type="primary"):
            on_approve(edited_comment.strip(), was_edited)

    with b2:
        if st.button("🔄 Regenerate", key=f"regen_{position}", use_container_width=True):
            st.session_state[regen_count_key] = st.session_state.get(regen_count_key, 0) + 1
            on_regenerate()

    with b3:
        if st.button("⏭️ Skip", key=f"skip_{position}", use_container_width=True):
            on_skip()

    with b4:
        save_label = f"💾 Save {approved_count} to Sheets" if approved_count > 0 else "💾 Save to Sheets"
        if st.button(save_label, key=f"save_{position}", use_container_width=True):
            on_save_to_master()

    regen_count = st.session_state.get(regen_count_key, 0)
    if regen_count > 0:
        st.caption(f"🔄 Regenerated {regen_count} time(s)")


def _fmt_currency(value) -> str:
    if value is None:
        return "N/A"
    try:
        num = float(str(value).replace("$", "").replace(",", "").strip())
        if num >= 1_000_000:
            return f"${num/1_000_000:.1f}M"
        if num >= 1_000:
            return f"${num/1_000:.0f}K"
        return f"${num:.0f}"
    except (ValueError, TypeError):
        return str(value) if value else "N/A"
