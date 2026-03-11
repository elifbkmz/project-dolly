"""
Multi-threading Risk Scorer.

Evaluates the number of executive contacts per account.
Single-threaded accounts are a churn risk — one relationship change = deal at risk.
Higher score = more risk.
"""

import logging
import re
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def parse_contact_count(value) -> Optional[int]:
    """
    Parse exec_contacts field into an integer count.

    Handles: integer (3), string ("3"), comma-separated list ("John, Mary, CEO"),
    semicolon-separated list, or None/NaN.

    Returns count (int ≥ 0) or None if data is missing.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "n/a", "-", ""):
        return None

    # If it's a pure number
    try:
        n = int(float(s))
        return max(0, n)
    except ValueError:
        pass

    # If it's a list of names/roles separated by commas or semicolons
    parts = re.split(r"[,;|\n]", s)
    non_empty = [p.strip() for p in parts if p.strip() and len(p.strip()) > 1]
    if non_empty:
        return len(non_empty)

    return None


def score_threading(row: pd.Series, scores_config: Optional[dict] = None) -> dict:
    """
    Compute threading risk score and tier for one account row.

    Args:
        row: Account row from the master DataFrame.
        scores_config: Dict from scoring_weights.yaml → threading_scores.

    Returns:
        Dict with:
            threading_score (float 0–100, higher = more risk)
            threading_tier  (str: "SINGLE" | "DUAL" | "MULTI")
            contact_count   (int or None)
            threading_missing (bool)
    """
    if scores_config is None:
        scores_config = {
            "zero_contacts": 100,
            "single_contact": 85,
            "dual_contacts": 40,
            "multi_contacts": 0,
            "missing_score": 70,
        }

    count = parse_contact_count(row.get("exec_contacts"))

    if count is None:
        return {
            "threading_score": float(scores_config.get("missing_score", 70)),
            "threading_tier": "UNKNOWN",
            "contact_count": None,
            "threading_missing": True,
        }

    if count == 0:
        score = float(scores_config.get("zero_contacts", 100))
        tier = "SINGLE"
    elif count == 1:
        score = float(scores_config.get("single_contact", 85))
        tier = "SINGLE"
    elif count == 2:
        score = float(scores_config.get("dual_contacts", 40))
        tier = "DUAL"
    else:
        score = float(scores_config.get("multi_contacts", 0))
        tier = "MULTI"

    return {
        "threading_score": score,
        "threading_tier": tier,
        "contact_count": count,
        "threading_missing": False,
    }


def get_threading_narrative(threading_tier: str, count: Optional[int]) -> str:
    """Short human-readable narrative for display."""
    if count is None:
        return "Contact data missing — assumed single-threaded (high risk)."
    if threading_tier == "SINGLE":
        return f"Single-threaded ({count} exec contact). One relationship change = deal at risk."
    if threading_tier == "DUAL":
        return f"Dual-threaded ({count} contacts). Adequate but needs a third exec touch."
    return f"Well multi-threaded ({count} contacts)."
