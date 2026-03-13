"""
Portfolio-level CRO comment generation.

Aggregates scored account data into regional portfolio metrics,
builds a portfolio user prompt, and generates a CRO-voice comment
for the Overview tab.
"""

import ast
import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from src.llm.client import call_claude, DEFAULT_MODEL

logger = logging.getLogger(__name__)


def aggregate_portfolio_metrics(scored_df: pd.DataFrame, region: str = "") -> dict:
    """
    Compute portfolio-level metrics from a scored DataFrame.

    Args:
        scored_df: DataFrame with scoring columns (attention_tier, nrr_tier,
                   arr, nrr_display, composite_score, etc.).
        region: If non-empty, filter to this region first.

    Returns:
        Dict with all placeholders needed by portfolio_prompt_template.
    """
    df = scored_df.copy()
    if region:
        df = df[df["region"].str.strip().str.upper() == region.strip().upper()]

    total_accounts = len(df)

    # ── P-tier counts ─────────────────────────────────────────────────────
    p1_count = int((df["attention_tier"] == "P1").sum())
    p2_count = int((df["attention_tier"] == "P2").sum())
    p3_count = int((df["attention_tier"] == "P3").sum())

    # ── ARR ───────────────────────────────────────────────────────────────
    total_arr = _sum_arr(df)
    total_arr_display = _format_arr(total_arr)

    # ── NRR ───────────────────────────────────────────────────────────────
    avg_nrr = _average_nrr(df)
    avg_nrr_display = f"{avg_nrr:.1f}%" if avg_nrr is not None else "N/A"

    # ── NRR distribution ──────────────────────────────────────────────────
    nrr_critical_count = int((df["nrr_tier"] == "CRITICAL").sum())
    nrr_at_risk_count = int((df["nrr_tier"] == "AT_RISK").sum())
    nrr_healthy_count = int((df["nrr_tier"] == "HEALTHY").sum())
    nrr_strong_count = int((df["nrr_tier"] == "STRONG").sum())

    # ── Top 5 accounts by composite score ─────────────────────────────────
    top_5_accounts = _format_top_accounts(df, n=5)

    # ── Upcoming renewals (within 90 days) ────────────────────────────────
    upcoming_renewals = _format_upcoming_renewals(df, days=90)

    # ── Competitor / whitespace opportunity counts ─────────────────────────
    competitor_opportunity_count = _count_nonempty_channel(df, "competitor_channels")
    whitespace_opportunity_count = _count_nonempty_channel(df, "whitespace_channels")
    displacement_count = _count_displacement(df)

    return {
        "region": region or "All Regions",
        "total_accounts": total_accounts,
        "total_arr": total_arr_display,
        "avg_nrr": avg_nrr_display,
        "p1_count": p1_count,
        "p2_count": p2_count,
        "p3_count": p3_count,
        "nrr_critical_count": nrr_critical_count,
        "nrr_at_risk_count": nrr_at_risk_count,
        "nrr_healthy_count": nrr_healthy_count,
        "nrr_strong_count": nrr_strong_count,
        "top_5_accounts": top_5_accounts,
        "upcoming_renewals": upcoming_renewals,
        "competitor_opportunity_count": competitor_opportunity_count,
        "whitespace_opportunity_count": whitespace_opportunity_count,
        "displacement_count": displacement_count,
    }


def build_portfolio_user_prompt(metrics: dict, templates: dict) -> str:
    """
    Format the portfolio user prompt from metrics and templates.

    Args:
        metrics: Output of aggregate_portfolio_metrics().
        templates: Loaded prompt_templates.yaml dict.

    Returns:
        Formatted user prompt string.
    """
    template = templates.get("portfolio_prompt_template", "")
    if not template:
        logger.warning("portfolio_prompt_template not found in templates config")
        return _fallback_portfolio_prompt(metrics)

    sentence_count = templates.get("sentence_count", "2-3")

    try:
        return template.format(
            sentence_count=sentence_count,
            **metrics,
        )
    except KeyError as exc:
        logger.warning("Portfolio prompt template missing placeholder: %s", exc)
        return _fallback_portfolio_prompt(metrics)


def generate_portfolio_comment(
    scored_df: pd.DataFrame,
    region: str,
    client,
    system_prompt: str,
    templates: dict,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
) -> str:
    """
    Generate a CRO portfolio comment for a region.

    Args:
        scored_df: Scored master DataFrame.
        region: Region to filter by (empty string = all regions).
        client: Initialized Anthropic client.
        system_prompt: Pre-built system prompt.
        templates: Loaded prompt_templates.yaml.
        model: Claude model identifier.
        temperature: Generation temperature.

    Returns:
        Generated portfolio comment text.
    """
    metrics = aggregate_portfolio_metrics(scored_df, region)
    user_prompt = build_portfolio_user_prompt(metrics, templates)

    comment = call_claude(
        client=client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=temperature,
    )
    return comment


# ── Internal helpers ──────────────────────────────────────────────────────────


def _clean_arr_value(value) -> float:
    """Parse a single ARR value to float, handling $, commas, and strings."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _sum_arr(df: pd.DataFrame) -> float:
    """Sum ARR across all accounts."""
    if "arr" not in df.columns or df.empty:
        return 0.0
    return sum(_clean_arr_value(v) for v in df["arr"])


def _format_arr(total: float) -> str:
    """Format total ARR as a dollar string."""
    if total >= 1_000_000:
        return f"${total / 1_000_000:.1f}M"
    if total >= 1_000:
        return f"${total:,.0f}"
    return f"${total:.0f}"


def _average_nrr(df: pd.DataFrame) -> Optional[float]:
    """Average NRR from the nrr_display column (strip % sign)."""
    if "nrr_display" not in df.columns or df.empty:
        return None
    values = []
    for v in df["nrr_display"]:
        try:
            values.append(float(str(v).replace("%", "").strip()))
        except (ValueError, TypeError):
            continue
    return sum(values) / len(values) if values else None


def _format_top_accounts(df: pd.DataFrame, n: int = 5) -> str:
    """Format top N accounts by composite score as a bullet list."""
    if df.empty:
        return "No accounts to display."

    top = df.nlargest(n, "composite_score")
    lines = []
    for _, row in top.iterrows():
        name = str(row.get("account_name", "Unknown")).strip()
        arr_display = _format_arr(_clean_arr_value(row.get("arr")))
        tier = str(row.get("attention_tier", "")).strip()
        signal = str(row.get("primary_signal", "")).strip()
        lines.append(f"- {name} | ARR: {arr_display} | {tier} | {signal}")
    return "\n".join(lines)


def _format_upcoming_renewals(df: pd.DataFrame, days: int = 90) -> str:
    """Format accounts with renewal dates within the given number of days."""
    if "renewal_date" not in df.columns or df.empty:
        return "No upcoming renewals."

    now = datetime.now()
    upcoming = []
    for _, row in df.iterrows():
        renewal_raw = row.get("renewal_date")
        if renewal_raw is None or (isinstance(renewal_raw, float) and pd.isna(renewal_raw)):
            continue
        s = str(renewal_raw).strip()
        if not s or s.lower() in ("nan", "none", ""):
            continue

        parsed_date = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %Y", "%b %Y"):
            try:
                parsed_date = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if parsed_date is None:
            continue

        delta = (parsed_date - now).days
        if 0 <= delta <= days:
            name = str(row.get("account_name", "Unknown")).strip()
            arr_display = _format_arr(_clean_arr_value(row.get("arr")))
            upcoming.append(f"- {name} | ARR: {arr_display} | Renews: {s} ({delta} days)")

    return "\n".join(upcoming) if upcoming else "No renewals within 90 days."


def _parse_channel_list(value) -> list:
    """Parse a channel list that may be a list or a string-serialized list."""
    if isinstance(value, list):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return []
    if s.startswith("["):
        try:
            return ast.literal_eval(s)
        except (ValueError, SyntaxError):
            return []
    return []


def _count_nonempty_channel(df: pd.DataFrame, column: str) -> int:
    """Count accounts with non-empty channel lists in the given column."""
    if column not in df.columns or df.empty:
        return 0
    count = 0
    for v in df[column]:
        channels = _parse_channel_list(v)
        if channels:
            count += 1
    return count


def _count_displacement(df: pd.DataFrame) -> int:
    """Count accounts with either competitor or whitespace channels (union)."""
    if df.empty:
        return 0
    count = 0
    for _, row in df.iterrows():
        has_competitor = bool(_parse_channel_list(row.get("competitor_channels")))
        has_whitespace = bool(_parse_channel_list(row.get("whitespace_channels")))
        if has_competitor or has_whitespace:
            count += 1
    return count


def _fallback_portfolio_prompt(metrics: dict) -> str:
    """Minimal fallback prompt if template formatting fails."""
    return (
        f"Review the portfolio for {metrics.get('region', 'the region')}. "
        f"{metrics.get('total_accounts', 0)} accounts, "
        f"ARR: {metrics.get('total_arr', 'N/A')}, "
        f"P1: {metrics.get('p1_count', 0)}, P2: {metrics.get('p2_count', 0)}, "
        f"P3: {metrics.get('p3_count', 0)}. "
        f"Write a 2-3 sentence strategic portfolio comment in your CRO voice."
    )
