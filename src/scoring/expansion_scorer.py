"""
Expansion Opportunity Scorer.

Scans Tech Stake channel columns to identify:
- White-space channels (None/blank): uncaptured revenue
- Competitor-held channels (Salesforce, Adobe, Inhouse, etc.): displacement targets

Higher score = more expansion opportunity = higher engagement priority.
"""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Default channel canonical names (subset of column_mappings.yaml)
DEFAULT_CHANNEL_COLUMNS = [
    "cdp",
    "marketing_automation",
    "email_promotional",
    "email_transactional",
    "sms_mms_rcs",
    "sms_transactional",
    "mobile_app_suite",
    "smart_recommender",
    "eureka_search",
    "whatsapp_marketing",
    "whatsapp_utility",
    "whatsapp_otp",
    "conversational_commerce",
    "customer_support_chatbot",
    "web_personalization",
    "analytics_insights",
]

# Friendly display names for channels
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


def _is_insider(value: str) -> bool:
    """True if the channel value indicates Insider One ownership."""
    return str(value).strip().lower() in ("insider one", "insider", "insider one ")


def _is_whitespace(value: str) -> bool:
    """True if the channel is uncaptured (blank, None, Not Applicable)."""
    v = str(value).strip().lower()
    return v in ("none", "not applicable", "n/a", "na", "not sure", "")


def _is_competitor(value: str, competitor_values: list[str]) -> bool:
    """True if the channel is held by a displaceable competitor."""
    v = str(value).strip().lower()
    return any(comp.lower() in v for comp in competitor_values)


def score_expansion(
    row: pd.Series,
    channel_columns: Optional[list[str]] = None,
    scores_config: Optional[dict] = None,
    column_mapping: Optional[dict] = None,
) -> dict:
    """
    Compute expansion opportunity score for one account row.

    Args:
        row: Account row from the master DataFrame.
        channel_columns: List of canonical channel column names to check.
        scores_config: Dict from scoring_weights.yaml → expansion_scores.
        column_mapping: Loaded column_mappings.yaml for whitespace/competitor value lists.

    Returns:
        Dict with:
            expansion_score       (float 0–100)
            expansion_tier        (str: "HIGH" | "MEDIUM" | "LOW")
            insider_product_count (int)
            total_channels        (int: channels present in data)
            competitor_channels   (list of {"channel": str, "vendor": str})
            whitespace_channels   (list of str: channel display names)
            expansion_channel_count (int: total displacement opportunities)
    """
    if scores_config is None:
        scores_config = {
            "whitespace_per_channel": 5,
            "competitor_per_channel": 8,
            "low_penetration_bonus": 10,
            "zero_products_bonus": 15,
            "low_penetration_arr_min": 50000,
            "max_score": 100,
        }
    if channel_columns is None:
        channel_columns = DEFAULT_CHANNEL_COLUMNS

    # Get value lists from column_mapping if provided
    if column_mapping:
        insider_values = column_mapping.get("insider_values", ["Insider One"])
        whitespace_values = column_mapping.get("whitespace_values", ["None", ""])
        competitor_values = column_mapping.get("competitor_values", ["Salesforce", "Adobe", "Inhouse"])
    else:
        insider_values = ["Insider One", "Insider", "insider one"]
        whitespace_values = ["None", "none", "Not Applicable", "Not sure", "N/A", "NA", ""]
        competitor_values = [
            "Salesforce", "Adobe", "Inhouse", "In House", "In-house",
            "HubSpot", "Hubspot", "Klaviyo", "Netcore", "Mixpanel",
            "Amplitude", "Braze", "Iterable", "MoEngage", "Algolia",
            "Zendesk", "Genesys",
        ]

    score = 0.0
    insider_count = 0
    insider_channels: list[str] = []
    competitor_channels: list[dict] = []
    whitespace_channels: list[str] = []
    total_channels = 0

    for col in channel_columns:
        if col not in row.index:
            continue
        raw = row[col]
        # Guard: if duplicate columns caused a Series to be returned, take first value
        if isinstance(raw, pd.Series):
            raw = raw.iloc[0] if not raw.empty else None
        value = str(raw).strip() if pd.notna(raw) else ""
        if not value:
            continue
        total_channels += 1
        display = CHANNEL_DISPLAY.get(col, col)

        if _is_insider(value):
            insider_count += 1
            insider_channels.append(display)
        elif _is_whitespace(value):
            score += scores_config.get("whitespace_per_channel", 5)
            whitespace_channels.append(display)
        elif _is_competitor(value, competitor_values):
            score += scores_config.get("competitor_per_channel", 8)
            competitor_channels.append({"channel": display, "vendor": value.strip()})
        # else: unknown/other — neutral

    # Bonuses for low Insider penetration
    arr = _parse_arr(row.get("arr"))
    arr_min = scores_config.get("low_penetration_arr_min", 50000)

    if insider_count == 0:
        score += scores_config.get("zero_products_bonus", 15)
    if insider_count < 3 and (arr is None or arr >= arr_min):
        score += scores_config.get("low_penetration_bonus", 10)

    max_score = scores_config.get("max_score", 100)
    score = min(max_score, max(0.0, score))

    high_threshold = 60
    medium_threshold = 30
    if score >= high_threshold:
        tier = "HIGH"
    elif score >= medium_threshold:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    return {
        "expansion_score": round(score, 1),
        "expansion_tier": tier,
        "insider_product_count": insider_count,
        "insider_channels": insider_channels,
        "total_channels": total_channels or len(channel_columns),
        "competitor_channels": competitor_channels,
        "whitespace_channels": whitespace_channels,
        "expansion_channel_count": len(competitor_channels) + len(whitespace_channels),
    }


def get_expansion_summary(competitor_channels: list[dict], whitespace_channels: list[str]) -> str:
    """Short human-readable summary for display."""
    parts = []
    if competitor_channels:
        competitors = ", ".join(f"{c['channel']}: {c['vendor']}" for c in competitor_channels[:3])
        parts.append(f"{len(competitor_channels)} competitor channel(s) ({competitors})")
    if whitespace_channels:
        wspace = ", ".join(whitespace_channels[:3])
        suffix = f"… +{len(whitespace_channels)-3} more" if len(whitespace_channels) > 3 else ""
        parts.append(f"{len(whitespace_channels)} white-space channel(s) ({wspace}{suffix})")
    return " | ".join(parts) if parts else "No significant expansion identified."


def _parse_arr(value) -> Optional[float]:
    """Parse ARR from string/numeric. Returns float or None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).replace("$", "").replace(",", "").replace("k", "000").strip()
    try:
        return float(s)
    except ValueError:
        return None
