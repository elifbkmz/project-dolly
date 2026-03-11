"""
Tech Stake visualization component.

Renders channel-by-channel product coverage as:
- Color-coded HTML chips for the Review Card
- Plotly stacked bar chart for the Dashboard
"""

import pandas as pd

CHANNEL_DISPLAY = {
    "cdp": "CDP",
    "marketing_automation": "Marketing Automation",
    "email_promotional": "Email (Promotional)",
    "email_transactional": "Email (Transactional)",
    "sms_mms_rcs": "SMS/MMS/RCS",
    "sms_transactional": "SMS (Transactional)",
    "mobile_app_suite": "Mobile App Suite",
    "smart_recommender": "Smart Recommender",
    "eureka_search": "Eureka Search",
    "whatsapp_marketing": "WhatsApp Marketing",
    "whatsapp_utility": "WhatsApp Utility",
    "whatsapp_otp": "WhatsApp OTP",
    "conversational_commerce": "Conversational Commerce",
    "customer_support_chatbot": "Customer Support Chatbot",
    "web_personalization": "Web Personalization / A/B Testing",
    "analytics_insights": "Analytics & Insights",
}

COLORS = {
    "insider": "#0d6efd",
    "competitor": "#dc3545",
    "whitespace": "#198754",
}


def _chip(text: str, color: str, bg: str) -> str:
    return (
        f'<span style="background:{bg}; color:{color}; border:1px solid {color}44; '
        f'padding:0.2rem 0.55rem; border-radius:12px; font-size:0.72rem; '
        f'font-weight:500; margin:0.15rem; display:inline-block;">{text}</span>'
    )


def render_channel_chips(scoring: dict) -> str:
    """
    Render the Tech Stake as colored HTML chips grouped by category.

    Args:
        scoring: Scoring dict with insider_channels, competitor_channels,
                 whitespace_channels, insider_product_count, total_channels.

    Returns:
        HTML string.
    """
    insider_count = scoring.get("insider_product_count", 0)
    total = scoring.get("total_channels", 16)
    insider_channels = scoring.get("insider_channels", [])
    competitor_channels = scoring.get("competitor_channels", [])
    whitespace_channels = scoring.get("whitespace_channels", [])

    sections = []

    # Insider One section — header + product chips
    sections.append(
        f'<div style="font-size:0.75rem; font-weight:700; color:#6ea8fe; '
        f'text-transform:uppercase; letter-spacing:0.06em; margin:0.75rem 0 0.35rem;">'
        f'📦 Insider One ({insider_count}/{total} channels)</div>'
    )
    if insider_channels:
        chips = "".join(
            _chip(ch, "#6ea8fe", "#0d6efd20")
            for ch in insider_channels
        )
        sections.append(f'<div style="margin-bottom:0.4rem;">{chips}</div>')
    elif insider_count == 0:
        sections.append(
            '<p style="color:#6c757d; font-size:0.82rem; margin:0.15rem 0 0.5rem;">'
            'No active Insider products detected.</p>'
        )

    # Competitor section
    if competitor_channels:
        chips = "".join(
            _chip(f"{c['channel']}: {c['vendor']}", "#ea868f", "#dc354520")
            for c in competitor_channels
        )
        sections.append(
            f'<div style="font-size:0.75rem; font-weight:700; color:#ea868f; '
            f'text-transform:uppercase; letter-spacing:0.06em; margin:0.75rem 0 0.35rem;">'
            f'🔴 Competitor-held ({len(competitor_channels)})</div>'
            f'<div>{chips}</div>'
        )

    # White Space section
    if whitespace_channels:
        chips = "".join(
            _chip(ch, "#75b798", "#19875420")
            for ch in whitespace_channels
        )
        sections.append(
            f'<div style="font-size:0.75rem; font-weight:700; color:#75b798; '
            f'text-transform:uppercase; letter-spacing:0.06em; margin:0.75rem 0 0.35rem;">'
            f'💚 White Space — Uncaptured ({len(whitespace_channels)})</div>'
            f'<div>{chips}</div>'
        )

    if not competitor_channels and not whitespace_channels:
        sections.append(
            '<p style="color:#6c757d; font-size:0.85rem;">No channel data available.</p>'
        )

    return "\n".join(sections)


def build_tech_stake_bar_chart(scored_df: pd.DataFrame):
    """
    Build a Plotly stacked horizontal bar showing channel coverage across all accounts.
    Returns a Plotly Figure for st.plotly_chart(), or None if plotly not available.
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None

    from src.scoring.expansion_scorer import (
        _is_insider, _is_whitespace, _is_competitor, DEFAULT_CHANNEL_COLUMNS
    )
    competitor_values = [
        "Salesforce", "Adobe", "Inhouse", "In House",
        "HubSpot", "Klaviyo", "Netcore", "Mixpanel",
    ]

    labels, insider_counts, competitor_counts, whitespace_counts = [], [], [], []
    for col in DEFAULT_CHANNEL_COLUMNS:
        if col not in scored_df.columns:
            continue
        values = scored_df[col].fillna("").astype(str)
        labels.append(CHANNEL_DISPLAY.get(col, col))
        insider_counts.append(values.apply(_is_insider).sum())
        whitespace_counts.append(values.apply(_is_whitespace).sum())
        competitor_counts.append(values.apply(lambda v: _is_competitor(v, competitor_values)).sum())

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Insider One", x=insider_counts, y=labels, orientation="h",
                         marker_color=COLORS["insider"]))
    fig.add_trace(go.Bar(name="Competitor", x=competitor_counts, y=labels, orientation="h",
                         marker_color=COLORS["competitor"]))
    fig.add_trace(go.Bar(name="White Space", x=whitespace_counts, y=labels, orientation="h",
                         marker_color=COLORS["whitespace"]))
    fig.update_layout(
        barmode="stack",
        title="Channel Coverage — All Accounts",
        plot_bgcolor="#0f0f1e",
        paper_bgcolor="#0f0f1e",
        font={"color": "#e2e8f0"},
        legend={"orientation": "h", "y": -0.15},
        height=520,
        margin={"l": 210, "r": 20, "t": 40, "b": 80},
    )
    return fig
