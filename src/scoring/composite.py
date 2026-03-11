"""
Composite Attention Score and P1/P2/P3 tier assignment.

Combines NRR risk, threading risk, and expansion opportunity scores
into a single "attention score" that determines review order.
"""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from src.scoring.nrr_scorer import score_nrr_risk
from src.scoring.threading_scorer import score_threading
from src.scoring.expansion_scorer import score_expansion

logger = logging.getLogger(__name__)


def compute_composite_score(
    nrr_result: dict,
    threading_result: dict,
    expansion_result: dict,
    weights: Optional[dict] = None,
    thresholds: Optional[dict] = None,
    row: Optional[pd.Series] = None,
) -> dict:
    """
    Combine sub-scores into a composite attention score.

    Args:
        nrr_result: Output of score_nrr_risk().
        threading_result: Output of score_threading().
        expansion_result: Output of score_expansion().
        weights: Dict with keys nrr, threading, expansion (default: 0.5, 0.25, 0.25).
        thresholds: Composite tier thresholds from scoring_weights.yaml.
        row: Account row for hard override checks (renewal_date, health_score).

    Returns:
        Dict with:
            composite_score (float 0–100)
            attention_tier  (str: "P1" | "P2" | "P3")
            primary_signal  (str: human-readable reason for tier)
            hard_override   (bool: True if P1 was forced by a hard condition)
    """
    if weights is None:
        weights = {"nrr": 0.50, "threading": 0.25, "expansion": 0.25}
    if thresholds is None:
        thresholds = {"p1_threshold": 65, "p2_threshold": 40, "renewal_days_p1": 90}

    nrr_score = nrr_result.get("nrr_score", 60.0)
    threading_score = threading_result.get("threading_score", 70.0)
    expansion_score = expansion_result.get("expansion_score", 0.0)

    composite = (
        nrr_score * weights.get("nrr", 0.5)
        + threading_score * weights.get("threading", 0.25)
        + expansion_score * weights.get("expansion", 0.25)
    )
    composite = round(min(100.0, max(0.0, composite)), 1)

    # Determine primary signal (which sub-score drove the result most)
    primary_signal = _get_primary_signal(nrr_result, threading_result, expansion_result)

    # Hard overrides — force P1 regardless of composite
    hard_override, override_reason = _check_hard_overrides(
        nrr_result, thresholds, row
    )

    if hard_override:
        tier = "P1"
        primary_signal = override_reason
    elif composite >= thresholds.get("p1_threshold", 65):
        tier = "P1"
    elif composite >= thresholds.get("p2_threshold", 40):
        tier = "P2"
    else:
        tier = "P3"

    return {
        "composite_score": composite,
        "attention_tier": tier,
        "primary_signal": primary_signal,
        "hard_override": hard_override,
    }


def score_all_accounts(
    df: pd.DataFrame,
    weights: Optional[dict] = None,
    thresholds: Optional[dict] = None,
    scoring_weights_config: Optional[dict] = None,
    column_mapping: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Apply scoring to every row in the master DataFrame.

    Args:
        df: Master account DataFrame (post-join, post-normalize).
        weights: Composite weights dict.
        thresholds: Composite tier thresholds.
        scoring_weights_config: Full scoring_weights.yaml content.
        column_mapping: Full column_mappings.yaml content (for expansion scorer).

    Returns:
        DataFrame with all scoring columns added, sorted by composite_score descending.
    """
    if df.empty:
        return df

    # Extract sub-configs from scoring_weights_config
    if scoring_weights_config:
        weights = weights or scoring_weights_config.get("weights", {})
        thresholds = thresholds or {
            **scoring_weights_config.get("composite_tiers", {}),
            "renewal_days_p1": scoring_weights_config.get("composite_tiers", {}).get("renewal_days_p1", 90),
        }
        nrr_thresholds = scoring_weights_config.get("nrr_thresholds", {})
        threading_scores = scoring_weights_config.get("threading_scores", {})
        expansion_scores = scoring_weights_config.get("expansion_scores", {})
    else:
        nrr_thresholds = threading_scores = expansion_scores = {}

    rows = []
    for _, row in df.iterrows():
        nrr_r = score_nrr_risk(row, nrr_thresholds or None)
        thread_r = score_threading(row, threading_scores or None)
        exp_r = score_expansion(row, column_mapping=column_mapping)
        comp_r = compute_composite_score(nrr_r, thread_r, exp_r, weights, thresholds, row)

        rows.append({
            **nrr_r,
            **thread_r,
            **exp_r,
            **comp_r,
        })

    scores_df = pd.DataFrame(rows, index=df.index)
    result = pd.concat([df, scores_df], axis=1)

    # Sort: P1 first by composite_score desc, then P2, then P3
    tier_order = {"P1": 0, "P2": 1, "P3": 2}
    result["_tier_sort"] = result["attention_tier"].map(tier_order).fillna(3)
    result = result.sort_values(
        ["_tier_sort", "composite_score"], ascending=[True, False]
    ).drop(columns=["_tier_sort"]).reset_index(drop=True)

    # Add global rank
    result.insert(0, "rank", range(1, len(result) + 1))

    logger.info(
        "Scored %d accounts: P1=%d, P2=%d, P3=%d",
        len(result),
        (result["attention_tier"] == "P1").sum(),
        (result["attention_tier"] == "P2").sum(),
        (result["attention_tier"] == "P3").sum(),
    )
    return result


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_primary_signal(nrr_result: dict, threading_result: dict, expansion_result: dict) -> str:
    """Return the most prominent risk/opportunity signal as a human-readable string."""
    nrr_tier = nrr_result.get("nrr_tier", "UNKNOWN")
    nrr_raw = nrr_result.get("nrr_raw")
    threading_tier = threading_result.get("threading_tier", "UNKNOWN")
    expansion_tier = expansion_result.get("expansion_tier", "LOW")

    if nrr_tier == "CRITICAL":
        return f"NRR CRITICAL ({nrr_raw:.0f}%)" if nrr_raw else "NRR CRITICAL (data missing)"
    if nrr_tier == "AT_RISK":
        return f"NRR AT RISK ({nrr_raw:.0f}%)" if nrr_raw else "NRR AT RISK"
    if threading_tier == "SINGLE":
        return "Single-threaded relationship"
    if expansion_tier == "HIGH":
        count = expansion_result.get("expansion_channel_count", 0)
        return f"High expansion opportunity ({count} channels)"
    if nrr_tier == "HEALTHY":
        return f"Healthy NRR ({nrr_raw:.0f}%)" if nrr_raw else "Healthy account"
    return "On track"


def _check_hard_overrides(
    nrr_result: dict,
    thresholds: dict,
    row: Optional[pd.Series],
) -> tuple[bool, str]:
    """
    Check conditions that force P1 regardless of composite score.

    Returns: (is_override: bool, reason: str)
    """
    # NRR critical
    if nrr_result.get("nrr_tier") == "CRITICAL":
        nrr = nrr_result.get("nrr_raw")
        return True, f"NRR CRITICAL ({nrr:.0f}%)" if nrr else "NRR CRITICAL"

    if row is None:
        return False, ""

    # Renewal imminent
    renewal_days_threshold = thresholds.get("renewal_days_p1", 90)
    renewal_days = _parse_renewal_days(row.get("renewal_date"))
    if renewal_days is not None and renewal_days < renewal_days_threshold:
        return True, f"Renewal in {renewal_days} days (< {renewal_days_threshold})"

    # Very low health score
    health = _parse_health_score(row.get("health_score"))
    if health is not None and health <= 2:
        return True, f"Health score critical ({health}/10)"

    return False, ""


def _parse_renewal_days(value) -> Optional[int]:
    """Parse renewal_date to days from today. Returns None if unparseable."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", ""):
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%B %Y", "%b %Y", "%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            delta = (dt - datetime.now()).days
            return delta
        except ValueError:
            continue
    return None


def _parse_health_score(value) -> Optional[float]:
    """Parse health score. Returns float or None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None
