"""
Review Card component — the centerpiece of the demo.

Renders one account card with a story-first layout:
- Header: tier badge, account name, AE, region
- Risk Summary: plain-language summary of why this account matters
- Key Facts: ARR, NRR, Renewal Date, Contacts (2x2 metrics)
- CRO Comment: divider, model label, text_area, regenerate button
- Scoring Details (collapsed): NRR badge, threading+expansion badges,
  tech stake chips, risk flags, deal stage/NRR tier/health caption

Action buttons (Approve, Skip, Save) are rendered by the caller.
"""

import streamlit as st
import pandas as pd
from pathlib import Path

from ui.components.risk_badges import (
    attention_tier_badge, nrr_badge, threading_badge,
    expansion_badge, build_risk_flags,
)
from ui.components.tech_stake_chart import render_channel_chips
from ui.components.risk_summary import build_risk_summary


def load_css():
    """Inject custom CSS into the Streamlit app (call once per session)."""
    css_path = Path(__file__).parent.parent / "styles" / "custom.css"
    if css_path.exists() and not st.session_state.get("_css_loaded"):
        st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)
        st.session_state["_css_loaded"] = True


def render_review_card(
    row: pd.Series,
    scoring: dict,
    account_key: str,
    generated_comment: str,
    on_regenerate,
    approved_count: int = 0,
    model: str = "claude-sonnet-4-6",
) -> str:
    """
    Render the account detail section using a story-first layout.

    Returns the current text in the comment text area (may be edited by user).
    Action buttons (Approve, Skip, Save) are rendered by the caller.
    """
    load_css()

    account_name = str(row.get("account_name", "Unknown")).strip()
    region = str(row.get("region", "")).strip()
    ae_name = str(row.get("ae_name", "N/A")).strip() or "N/A"
    territory = str(row.get("territory", "")).strip()
    attention_tier = scoring.get("attention_tier", "P2")
    nrr_display = scoring.get("nrr_display", "N/A")
    nrr_tier = scoring.get("nrr_tier", "UNKNOWN")

    # ── 1. Header ─────────────────────────────────────────────────────────
    tier_html = attention_tier_badge(attention_tier)
    region_meta = region
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

    # ── 2. Risk Summary ───────────────────────────────────────────────────
    _tier_colors = {"P1": "#dc3545", "P2": "#fd7e14", "P3": "#198754"}
    border_color = _tier_colors.get(attention_tier, "#6c757d")
    risk_text = build_risk_summary(row, scoring)
    st.markdown(
        f'<div class="risk-summary" style="border-left-color:{border_color};">'
        f"{risk_text}</div>",
        unsafe_allow_html=True,
    )

    # ── 3. Key Facts ──────────────────────────────────────────────────────
    arr_display = _fmt_currency(row.get("arr"))
    renewal_date = str(row.get("renewal_date", "N/A")).strip() or "N/A"
    contact_count = scoring.get("contact_count")
    contacts_display = str(contact_count) if contact_count is not None else "N/A"

    r1c1, r1c2 = st.columns(2)
    r1c1.metric("ARR", arr_display)
    r1c2.metric("NRR", str(nrr_display))

    r2c1, r2c2 = st.columns(2)
    r2c1.metric("Renewal Date", renewal_date)
    r2c2.metric("Contacts", contacts_display)

    # ── 4. CRO Comment ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown(f"**CRO Suggested Comment** *({model})*")

    comment_area_key = f"comment_area_{account_key}"
    regen_count_key = f"regen_{account_key}"

    if comment_area_key not in st.session_state:
        st.session_state[comment_area_key] = generated_comment

    edited_comment = st.text_area(
        "Edit before approving:",
        value=st.session_state[comment_area_key],
        height=140,
        key=comment_area_key,
        help="The AI-generated comment. Modify freely before approving.",
    )

    if st.button("Regenerate", key=f"regen_btn_{account_key}"):
        st.session_state[regen_count_key] = st.session_state.get(regen_count_key, 0) + 1
        on_regenerate()

    regen_count = st.session_state.get(regen_count_key, 0)
    if regen_count > 0:
        st.caption(f"Regenerated {regen_count} time(s)")

    # ── 5. Scoring Details (collapsed) ────────────────────────────────────
    deal_stage = str(row.get("deal_stage", "N/A")).strip() or "N/A"
    health_raw = str(row.get("health_score", "")).strip()
    health_display = health_raw if health_raw and health_raw not in ("nan", "") else "N/A"

    with st.expander("Scoring Details", expanded=False):
        nrr_html = nrr_badge(nrr_display, scoring.get("nrr_tier", "UNKNOWN"))
        badges_html = (
            nrr_html
            + "&nbsp;&nbsp;"
            + threading_badge(scoring.get("threading_tier", "UNKNOWN"), contact_count)
            + "&nbsp;&nbsp;"
            + expansion_badge(
                scoring.get("expansion_tier", "LOW"),
                float(scoring.get("expansion_score", 0) or 0),
            )
        )
        st.markdown(f"<div style='margin:0.5rem 0;'>{badges_html}</div>", unsafe_allow_html=True)
        st.markdown(render_channel_chips(scoring), unsafe_allow_html=True)
        st.markdown(build_risk_flags(scoring), unsafe_allow_html=True)
        st.caption(
            f"**Stage:** {deal_stage} &nbsp;|&nbsp; **NRR Tier:** {nrr_tier} &nbsp;|&nbsp; **Health:** {health_display}"
        )

    return edited_comment


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
