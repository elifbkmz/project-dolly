"""
Risk badge and label components for the Streamlit Review Card.

Renders color-coded tier labels, NRR badges, threading status, and risk flags
as HTML strings injected via st.markdown(..., unsafe_allow_html=True).
"""

TIER_EMOJI = {"P1": "🔴", "P2": "🟡", "P3": "🟢"}
NRR_TIER_EMOJI = {
    "CRITICAL": "🔴", "AT_RISK": "🟡",
    "HEALTHY": "🟢", "STRONG": "💚", "UNKNOWN": "⚪",
}
THREADING_EMOJI = {"SINGLE": "⚠️", "DUAL": "🔷", "MULTI": "✅", "UNKNOWN": "❓"}


def attention_tier_badge(tier: str) -> str:
    emoji = TIER_EMOJI.get(tier, "⚪")
    colors = {"P1": "#dc3545", "P2": "#fd7e14", "P3": "#198754"}
    color = colors.get(tier, "#6c757d")
    return (
        f'<span style="background:{color}; color:white; padding:0.25rem 0.75rem; '
        f'border-radius:20px; font-size:0.75rem; font-weight:700; '
        f'letter-spacing:0.05em; text-transform:uppercase;">'
        f'{emoji} {tier}</span>'
    )


def nrr_badge(nrr_display: str, nrr_tier: str) -> str:
    emoji = NRR_TIER_EMOJI.get(nrr_tier, "⚪")
    colors = {
        "CRITICAL": "#dc3545", "AT_RISK": "#ffc107",
        "HEALTHY": "#198754", "STRONG": "#0dcaf0", "UNKNOWN": "#6c757d",
    }
    color = colors.get(nrr_tier, "#6c757d")
    return (
        f'<span style="background:{color}22; color:{color}; border:1px solid {color}44; '
        f'padding:0.2rem 0.6rem; border-radius:12px; font-size:0.8rem; font-weight:600;">'
        f'{emoji} {nrr_display} [{nrr_tier}]</span>'
    )


def threading_badge(threading_tier: str, contact_count) -> str:
    emoji = THREADING_EMOJI.get(threading_tier, "❓")
    colors = {"SINGLE": "#dc3545", "DUAL": "#fd7e14", "MULTI": "#198754", "UNKNOWN": "#6c757d"}
    color = colors.get(threading_tier, "#6c757d")
    count_str = f" ({contact_count} contacts)" if contact_count is not None else ""
    return (
        f'<span style="background:{color}22; color:{color}; border:1px solid {color}44; '
        f'padding:0.2rem 0.6rem; border-radius:12px; font-size:0.8rem; font-weight:600;">'
        f'{emoji} {threading_tier}{count_str}</span>'
    )


def expansion_badge(expansion_tier: str, expansion_score: float) -> str:
    emoji = {"HIGH": "🎯", "MEDIUM": "📈", "LOW": "➡️"}.get(expansion_tier, "")
    colors = {"HIGH": "#198754", "MEDIUM": "#fd7e14", "LOW": "#6c757d"}
    color = colors.get(expansion_tier, "#6c757d")
    return (
        f'<span style="background:{color}22; color:{color}; border:1px solid {color}44; '
        f'padding:0.2rem 0.6rem; border-radius:12px; font-size:0.8rem; font-weight:600;">'
        f'{emoji} Expansion: {expansion_tier} ({expansion_score:.0f}/100)</span>'
    )


def build_risk_flags(scoring: dict) -> str:
    """Build the full risk flags block for one account as HTML."""
    flags = []

    nrr_tier = scoring.get("nrr_tier", "UNKNOWN")
    nrr_display = scoring.get("nrr_display", "N/A")
    threading_tier = scoring.get("threading_tier", "UNKNOWN")
    expansion_tier = scoring.get("expansion_tier", "LOW")
    expansion_count = scoring.get("expansion_channel_count", 0)

    def flag(icon, text, bg, color):
        return (
            f'<div style="background:{bg}; color:{color}; padding:0.35rem 0.75rem; '
            f'border-radius:6px; font-size:0.85rem; margin-bottom:0.35rem;">'
            f'{icon} {text}</div>'
        )

    if nrr_tier == "CRITICAL":
        flags.append(flag("🔴", f"NRR CRITICAL at {nrr_display} — immediate action required", "#dc354515", "#ea868f"))
    elif nrr_tier == "AT_RISK":
        flags.append(flag("🟡", f"NRR AT RISK at {nrr_display} — account is contracting", "#ffc10715", "#ffda6a"))
    elif nrr_tier in ("HEALTHY", "STRONG"):
        flags.append(flag("✅", f"NRR {nrr_display} — {nrr_tier.lower()}", "#19875415", "#75b798"))

    if threading_tier == "SINGLE":
        count = scoring.get("contact_count")
        count_str = f" ({count} contact)" if count is not None else ""
        flags.append(flag("⚠️", f"Single-threaded{count_str} — one relationship change = deal at risk", "#ffc10715", "#ffda6a"))
    elif threading_tier == "DUAL":
        flags.append(flag("🔷", "Dual-threaded — add a third exec contact", "#fd7e1415", "#feb272"))
    elif threading_tier == "MULTI":
        flags.append(flag("✅", "Well multi-threaded", "#19875415", "#75b798"))

    if expansion_tier == "HIGH":
        flags.append(flag("🎯", f"HIGH expansion potential — {expansion_count} channels to capture or displace", "#19875415", "#75b798"))
    elif expansion_tier == "MEDIUM":
        flags.append(flag("📈", f"MEDIUM expansion potential — {expansion_count} channels", "#fd7e1415", "#feb272"))

    if not flags:
        flags.append(flag("➡️", "No major risk signals identified", "#6c757d15", "#9ca3af"))

    return "\n".join(flags)
