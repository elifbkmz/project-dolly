"""
NRR Risk Scorer.

Converts a raw NRR percentage into a risk score (0–100) and tier label.
Higher score = more risk = more CRO attention required.
"""

import logging
import re
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def parse_nrr(value) -> Optional[float]:
    """
    Parse NRR from various formats: "87%", "0.87", "87", 87, None.

    Returns a float percentage (e.g., 87.0) or None if unparseable.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "n/a", "-", ""):
        return None
    # Remove % sign
    s = s.replace("%", "").strip()
    try:
        num = float(s)
        # If value is a decimal fraction (0–2 range), convert to percentage
        if 0 < num <= 2.0:
            num = num * 100
        # If value looks like an MRR growth rate (small number, e.g. -20 to 50)
        # rather than a real NRR percentage (usually 60–150), shift to NRR scale.
        # e.g. "5.00%" growth → NRR of 105%; "-10%" growth → NRR of 90%.
        if -100.0 < num < 50.0:
            num = num + 100.0
        return num
    except ValueError:
        logger.debug("Could not parse NRR value: '%s'", value)
        return None


def score_nrr_risk(row: pd.Series, thresholds: Optional[dict] = None) -> dict:
    """
    Compute NRR risk score and tier for one account row.

    Args:
        row: Account row from the master DataFrame.
        thresholds: Dict from scoring_weights.yaml → nrr_thresholds.
                    Defaults to standard thresholds if None.

    Returns:
        Dict with:
            nrr_score (float 0–100, higher = more risk)
            nrr_tier  (str: "CRITICAL" | "AT_RISK" | "HEALTHY" | "STRONG" | "UNKNOWN")
            nrr_raw   (float or None)
            nrr_missing (bool)
            nrr_display (str: formatted for UI display)
    """
    if thresholds is None:
        thresholds = {
            "critical": 90.0,
            "at_risk": 100.0,
            "healthy": 110.0,
            "missing_score": 60.0,
        }

    critical = thresholds.get("critical", 90.0)
    at_risk = thresholds.get("at_risk", 100.0)
    healthy = thresholds.get("healthy", 110.0)
    missing_score = thresholds.get("missing_score", 60.0)

    raw_nrr = row.get("nrr")
    # Guard: duplicate column could return a Series; take first value
    if isinstance(raw_nrr, pd.Series):
        raw_nrr = raw_nrr.iloc[0] if not raw_nrr.empty else None
    nrr = parse_nrr(raw_nrr)

    if nrr is None:
        return {
            "nrr_score": missing_score,
            "nrr_tier": "UNKNOWN",
            "nrr_raw": None,
            "nrr_missing": True,
            "nrr_display": "N/A",
        }

    # Calculate score
    if nrr < critical:
        # CRITICAL: score ranges from ~55 at 90% to ~100 at very low NRR
        score = min(100.0, 55.0 + (critical - nrr) * 1.5)
        tier = "CRITICAL"
    elif nrr < at_risk:
        # AT_RISK: score ranges from ~30 to ~55
        score = 30.0 + (at_risk - nrr) * 2.5
        tier = "AT_RISK"
    elif nrr < healthy:
        # HEALTHY: score ranges from ~5 to ~30
        score = 5.0 + (healthy - nrr) * 2.5
        tier = "HEALTHY"
    else:
        # STRONG: score approaches 0
        score = max(0.0, 5.0 - (nrr - healthy) * 0.25)
        tier = "STRONG"

    score = max(0.0, min(100.0, score))

    return {
        "nrr_score": round(score, 1),
        "nrr_tier": tier,
        "nrr_raw": nrr,
        "nrr_missing": False,
        "nrr_display": f"{nrr:.0f}%",
    }


def get_nrr_narrative(nrr_tier: str, nrr_raw: Optional[float]) -> str:
    """Short human-readable narrative for the CLI/UI display."""
    if nrr_raw is None:
        return "NRR data missing — assumed at risk."
    narratives = {
        "CRITICAL": f"NRR at {nrr_raw:.0f}% — account is contracting. Immediate action required.",
        "AT_RISK": f"NRR at {nrr_raw:.0f}% — below 100%, not fully renewing. Monitor closely.",
        "HEALTHY": f"NRR at {nrr_raw:.0f}% — healthy expansion.",
        "STRONG": f"NRR at {nrr_raw:.0f}% — strong growth signal.",
    }
    return narratives.get(nrr_tier, f"NRR: {nrr_raw:.0f}%")
