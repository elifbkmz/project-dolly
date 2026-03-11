"""
Prompt builder for CRO-voice comment generation.

Assembles structured system and user prompts from:
- CRO persona config (cro_persona.yaml)
- Prompt templates (prompt_templates.yaml)
- Tone profile (cro_tone_profile.yaml — few-shot examples)
- Account row data + scoring results
"""

import logging
from typing import Optional

import pandas as pd

from src.ingestion.tone_scraper import format_tone_for_prompt

logger = logging.getLogger(__name__)


def build_system_prompt(
    templates: dict,
    cro_config: dict,
    tone_profile: Optional[dict] = None,
) -> str:
    """
    Build the Claude system prompt.

    Args:
        templates: Loaded prompt_templates.yaml.
        cro_config: Loaded cro_persona.yaml.
        tone_profile: Loaded cro_tone_profile.yaml (None if not yet generated).

    Returns:
        Formatted system prompt string.
    """
    cro = cro_config.get("cro", {})
    philosophy = cro_config.get("philosophy", "")
    voice_rules = cro_config.get("voice_rules", [])

    voice_rules_text = "\n".join(f"- {rule}" for rule in voice_rules)

    # Tone calibration section (injected as few-shot examples)
    tone_section = ""
    if tone_profile and tone_profile.get("generated"):
        tone_section = format_tone_for_prompt(tone_profile, max_examples=5)

    template = templates.get(
        "system_prompt_template",
        "You are {cro_name}, {cro_title} at {company_name}.\n\n{cro_philosophy}\n\n{voice_rules}\n\n{tone_calibration_section}",
    )

    return template.format(
        cro_name=cro.get("name", "CRO"),
        cro_title=cro.get("title", "Chief Revenue Officer"),
        company_name=cro.get("company", "the company"),
        cro_philosophy=philosophy,
        voice_rules=voice_rules_text,
        tone_calibration_section=tone_section,
    )


def build_account_user_prompt(
    row: pd.Series,
    scoring: dict,
    templates: dict,
) -> str:
    """
    Build the per-account user prompt with all relevant context.

    Args:
        row: Account row from the scored master DataFrame.
        scoring: Dict containing all scoring sub-results for this row.
        templates: Loaded prompt_templates.yaml.

    Returns:
        Formatted user prompt string.
    """
    # Extract channel context
    channel_ctx = extract_channel_context(row, scoring)

    # Format ARR
    arr_raw = row.get("arr")
    arr_display = _format_currency(arr_raw)

    # Format NRR
    nrr_display = scoring.get("nrr_display", "N/A")
    nrr_tier = scoring.get("nrr_tier", "UNKNOWN")

    # Format renewal
    renewal_date = str(row.get("renewal_date", "N/A")).strip() or "N/A"
    renewal_days_out = scoring.get("_renewal_days", None)
    renewal_days_str = f"{renewal_days_out}" if renewal_days_out is not None else "?"

    # Health and stage
    health_raw = row.get("health_score", "")
    health_display = str(health_raw).strip() if health_raw and str(health_raw).strip() not in ("nan", "") else "N/A"
    deal_stage = str(row.get("deal_stage", "N/A")).strip() or "N/A"

    # Threading
    contact_count = scoring.get("contact_count")
    contact_display = str(contact_count) if contact_count is not None else "Unknown"
    threading_tier = scoring.get("threading_tier", "UNKNOWN")

    # Competitors / whitespace / insider product names
    competitor_channels = channel_ctx.get("competitor_channels", [])
    whitespace_channels = channel_ctx.get("whitespace_channels", [])
    insider_channels = channel_ctx.get("insider_channels", [])
    competitor_display = (
        ", ".join(f"{c['channel']}: {c['vendor']}" for c in competitor_channels)
        if competitor_channels else "None identified"
    )
    whitespace_display = (
        ", ".join(whitespace_channels) if whitespace_channels else "None identified"
    )
    insider_channels_display = (
        ", ".join(insider_channels) if insider_channels else "None detected"
    )

    # Coexisting competitors
    coexisting = str(row.get("coexisting_competitors", row.get("do they have co existing competitor", ""))).strip()
    coexisting = coexisting if coexisting and coexisting.lower() not in ("nan", "") else "None noted"

    # ── Maps tab rich fields ──────────────────────────────────────────────────
    def _clean(key: str, fallback: str = "N/A") -> str:
        """Extract a string field from the row, returning fallback if missing/empty."""
        val = row.get(key, "")
        if isinstance(val, pd.Series):
            val = val.iloc[0] if not val.empty else ""
        s = str(val).strip()
        return s if s and s.lower() not in ("nan", "none", "") else fallback

    next_steps = _clean("next_steps")
    competitive_strategy = _clean("competitive_strategy")
    focus_product = _clean("focus_product")
    estimated_amount = _clean("estimated_amount")
    estimated_closing_date = _clean("estimated_closing_date")
    acquisition_type = _clean("acquisition_type")
    auto_renewal = _clean("auto_renewal")
    csm_name = _clean("csm_name")
    csm_approval = _clean("csm_approval")
    customer_lifetime = _clean("customer_lifetime")
    insider_utilization = _clean("insider_utilization")

    template = templates.get("user_prompt_template", _default_user_template())

    try:
        return template.format(
            account_name=str(row.get("account_name", "Unknown")).strip(),
            region=str(row.get("region", "Unknown")).strip(),
            ae_name=str(row.get("ae_name", "N/A")).strip() or "N/A",
            csm_name=csm_name,
            arr_display=arr_display,
            nrr_display=nrr_display,
            nrr_tier=nrr_tier,
            renewal_date=renewal_date,
            renewal_days_out=renewal_days_str,
            auto_renewal=auto_renewal,
            health_score=health_display,
            deal_stage=deal_stage,
            focus_product=focus_product,
            acquisition_type=acquisition_type,
            estimated_amount=estimated_amount,
            estimated_closing_date=estimated_closing_date,
            customer_lifetime=customer_lifetime,
            contact_count=contact_display,
            threading_tier=threading_tier,
            insider_product_count=channel_ctx.get("insider_count", 0),
            insider_channels_display=insider_channels_display,
            insider_utilization=insider_utilization,
            total_channels=channel_ctx.get("total_channels", 16),
            competitor_channels_display=competitor_display,
            whitespace_channels_display=whitespace_display,
            coexisting_competitors=coexisting,
            next_steps=next_steps,
            competitive_strategy=competitive_strategy,
            csm_approval=csm_approval,
            attention_tier=scoring.get("attention_tier", "P2"),
            primary_signal=scoring.get("primary_signal", "N/A"),
            nrr_score=scoring.get("nrr_score", 0),
            threading_score=scoring.get("threading_score", 0),
            expansion_score=scoring.get("expansion_score", 0),
            sentence_count=templates.get("sentence_count", "2-3"),
        )
    except KeyError as exc:
        logger.warning("Prompt template missing placeholder: %s", exc)
        return _fallback_prompt(row, scoring, channel_ctx)


def extract_channel_context(row: pd.Series, scoring: dict) -> dict:
    """
    Pull structured channel context from the scoring result.

    Args:
        row: Account row.
        scoring: Scoring results dict from composite scorer.

    Returns:
        Dict with insider_count, insider_channels, competitor_channels,
        whitespace_channels, total_channels.
    """
    return {
        "insider_count": scoring.get("insider_product_count", 0),
        "insider_channels": scoring.get("insider_channels", []),
        "competitor_channels": scoring.get("competitor_channels", []),
        "whitespace_channels": scoring.get("whitespace_channels", []),
        "total_channels": scoring.get("total_channels", 16),
    }


def _format_currency(value) -> str:
    """Format ARR value as dollar string."""
    if value is None:
        return "N/A"
    try:
        num = float(str(value).replace("$", "").replace(",", "").strip())
        if num >= 1_000_000:
            return f"${num/1_000_000:.1f}M"
        if num >= 1_000:
            return f"${num:,.0f}"
        return f"${num:.0f}"
    except (ValueError, TypeError):
        return str(value)


def _default_user_template() -> str:
    return """Review this account and write your {sentence_count}-sentence CRO comment.

ACCOUNT: {account_name}
REGION: {region}
AE: {ae_name}

FINANCIALS:
- ARR: {arr_display}
- NRR: {nrr_display}  [{nrr_tier}]
- Renewal: {renewal_date} ({renewal_days_out} days out)
- Focus / Health: {health_score}
- Deal Stage: {deal_stage}

RELATIONSHIP:
- Executive Contacts: {contact_count} [{threading_tier}]

TECH STAKE — Insider One coverage:
- Insider Products Active: {insider_product_count} of {total_channels} channels
- Active Insider Products: {insider_channels_display}
- Competitor-held channels: {competitor_channels_display}
- White-space channels (uncaptured): {whitespace_channels_display}
- Co-existing competitors noted: {coexisting_competitors}

RISK SIGNALS:
- Attention Tier: {attention_tier}
- Primary driver: {primary_signal}
- NRR Score: {nrr_score:.0f}/100  |  Threading Score: {threading_score:.0f}/100  |  Expansion Score: {expansion_score:.0f}/100

Write your CRO comment now. Be specific. Name channels and numbers.
Do not use bullet points or headers. Output only the comment text, nothing else."""


def _fallback_prompt(row: pd.Series, scoring: dict, channel_ctx: dict) -> str:
    """Minimal fallback prompt if template formatting fails."""
    return (
        f"Review account '{row.get('account_name', 'Unknown')}' in {row.get('region', 'N/A')}. "
        f"NRR: {scoring.get('nrr_display', 'N/A')}, Tier: {scoring.get('attention_tier', 'P2')}. "
        f"Write a 2-3 sentence strategic comment in your CRO voice."
    )
