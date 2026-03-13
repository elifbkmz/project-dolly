"""
Tech-stake CRO comment generation.

Detects vendor gaps (competitor-held and whitespace channels),
filters accounts with displacement opportunities, and generates
CRO-voice comments focused on tech stack analysis.
"""

import ast
import logging
from typing import List

import pandas as pd

from src.llm.client import call_claude, DEFAULT_MODEL
from src.llm.prompt_builder import extract_channel_context

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _ensure_list(val) -> list:
    """
    Coerce a value to a list.

    - If already a list, return as-is.
    - If a string starting with '[', parse via ast.literal_eval.
    - Otherwise return [].
    """
    if isinstance(val, list):
        return val
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return []
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return []
    if s.startswith("["):
        try:
            return ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return []
    return []


def _clean_arr_value(value) -> float:
    """Parse a single ARR value to float, handling $, commas, and strings."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


# ── Public API ───────────────────────────────────────────────────────────────


def detect_vendor_gaps(row: pd.Series) -> dict:
    """
    Detect competitor-held and whitespace channel gaps for an account.

    Args:
        row: Account row containing competitor_channels and whitespace_channels.

    Returns:
        Dict with keys:
            competitor_gaps (list[str]): formatted "Channel: Vendor" strings
            whitespace_gaps (list[str]): channel names with no vendor
            has_gaps (bool): True if any gaps exist
            gap_count (int): total number of gaps
    """
    # Parse competitor channels
    raw_competitors = _ensure_list(row.get("competitor_channels"))
    competitor_gaps: List[str] = []
    for entry in raw_competitors:
        if isinstance(entry, dict):
            channel = entry.get("channel", "Unknown")
            vendor = entry.get("vendor", "Unknown")
            competitor_gaps.append(f"{channel}: {vendor}")
        elif isinstance(entry, str) and entry.strip():
            competitor_gaps.append(entry.strip())

    # Parse whitespace channels
    whitespace_gaps: List[str] = _ensure_list(row.get("whitespace_channels"))

    gap_count = len(competitor_gaps) + len(whitespace_gaps)

    return {
        "competitor_gaps": competitor_gaps,
        "whitespace_gaps": whitespace_gaps,
        "has_gaps": gap_count > 0,
        "gap_count": gap_count,
    }


def filter_accounts_with_gaps(
    scored_df: pd.DataFrame,
    min_arr: float = 5000,
    region: str = "",
) -> pd.DataFrame:
    """
    Filter scored accounts to those with vendor/whitespace gaps.

    Args:
        scored_df: Scored master DataFrame.
        min_arr: Minimum ARR threshold (after cleaning $, commas).
        region: If non-empty, filter to this region first.

    Returns:
        Filtered DataFrame sorted by ARR descending, index reset.
    """
    df = scored_df.copy()

    # Region filter
    if region:
        df = df[df["region"].str.strip().str.upper() == region.strip().upper()]

    # Keep only accounts with gaps
    has_gap_mask = df.apply(lambda r: detect_vendor_gaps(r)["has_gaps"], axis=1)
    df = df[has_gap_mask]

    # ARR filter
    df = df.copy()
    df["_arr_numeric"] = df["arr"].apply(_clean_arr_value)
    df = df[df["_arr_numeric"] >= min_arr]

    # Sort by ARR descending
    df = df.sort_values("_arr_numeric", ascending=False)

    # Clean up helper column
    df = df.drop(columns=["_arr_numeric"])

    return df.reset_index(drop=True)


def build_tech_stake_user_prompt(
    row: pd.Series,
    scoring: dict,
    templates: dict,
) -> str:
    """
    Build the per-account user prompt for tech stake comment generation.

    Args:
        row: Account row from the scored master DataFrame.
        scoring: Dict containing all scoring sub-results for this row.
        templates: Loaded prompt_templates.yaml dict.

    Returns:
        Formatted user prompt string.
    """
    # Channel context from scoring
    channel_ctx = extract_channel_context(row, scoring)

    # Vendor gaps from raw row data
    gaps = detect_vendor_gaps(row)

    # Format ARR
    arr_raw = row.get("arr")
    arr_display = _format_currency(arr_raw)

    # NRR display
    nrr_display = scoring.get("nrr_display", "N/A")

    # Format gap lists as bulleted text
    if gaps["competitor_gaps"]:
        vendor_gaps_text = "\n".join(f"  - {g}" for g in gaps["competitor_gaps"])
    else:
        vendor_gaps_text = "  None identified"

    if gaps["whitespace_gaps"]:
        whitespace_gaps_text = "\n".join(f"  - {g}" for g in gaps["whitespace_gaps"])
    else:
        whitespace_gaps_text = "  None identified"

    # Insider channels display
    insider_channels = channel_ctx.get("insider_channels", [])
    insider_channels_display = (
        ", ".join(insider_channels) if insider_channels else "None detected"
    )

    # Coexisting competitors
    coexisting = str(
        row.get("coexisting_competitors", row.get("do they have co existing competitor", ""))
    ).strip()
    coexisting = coexisting if coexisting and coexisting.lower() not in ("nan", "") else "None noted"

    template = templates.get("tech_stake_prompt_template", "")
    if not template:
        logger.warning("tech_stake_prompt_template not found in templates config")
        return _fallback_tech_stake_prompt(row, scoring, gaps)

    sentence_count = templates.get("sentence_count", "2-3")

    try:
        return template.format(
            sentence_count=sentence_count,
            account_name=str(row.get("account_name", "Unknown")).strip(),
            region=str(row.get("region", "Unknown")).strip(),
            ae_name=str(row.get("ae_name", "N/A")).strip() or "N/A",
            arr_display=arr_display,
            nrr_display=nrr_display,
            insider_product_count=channel_ctx.get("insider_count", 0),
            total_channels=channel_ctx.get("total_channels", 16),
            insider_channels_display=insider_channels_display,
            vendor_gaps=vendor_gaps_text,
            whitespace_gaps=whitespace_gaps_text,
            coexisting_competitors=coexisting,
        )
    except KeyError as exc:
        logger.warning("Tech stake prompt template missing placeholder: %s", exc)
        return _fallback_tech_stake_prompt(row, scoring, gaps)


def generate_tech_stake_comment(
    row: pd.Series,
    scoring: dict,
    client,
    system_prompt: str,
    templates: dict,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
) -> str:
    """
    Generate a CRO tech stake comment for a single account.

    Args:
        row: Account row from the scored master DataFrame.
        scoring: Scoring results dict for this account.
        client: Initialized Anthropic client.
        system_prompt: Pre-built system prompt.
        templates: Loaded prompt_templates.yaml.
        model: Claude model identifier.
        temperature: Generation temperature.

    Returns:
        Generated tech stake comment text.
    """
    user_prompt = build_tech_stake_user_prompt(row, scoring, templates)

    comment = call_claude(
        client=client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=temperature,
    )
    return comment


# ── Internal helpers ─────────────────────────────────────────────────────────


def _format_currency(value) -> str:
    """Format ARR value as dollar string."""
    if value is None:
        return "N/A"
    try:
        num = float(str(value).replace("$", "").replace(",", "").strip())
        if num >= 1_000_000:
            return f"${num / 1_000_000:.1f}M"
        if num >= 1_000:
            return f"${num:,.0f}"
        return f"${num:.0f}"
    except (ValueError, TypeError):
        return str(value)


def _fallback_tech_stake_prompt(row: pd.Series, scoring: dict, gaps: dict) -> str:
    """Minimal fallback prompt if template formatting fails."""
    return (
        f"Review the tech stack for account '{row.get('account_name', 'Unknown')}' "
        f"in {row.get('region', 'N/A')}. "
        f"{gaps['gap_count']} vendor/whitespace gaps detected. "
        f"Write a 2-3 sentence strategic comment about displacement opportunities "
        f"in your CRO voice."
    )
