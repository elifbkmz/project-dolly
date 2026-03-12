"""
Deterministic plain-language risk summary generator.

Turns scoring data + row data into a single human-readable sentence
explaining why an account matters. Not an LLM call — pure template logic.
"""

import ast
from typing import List

import pandas as pd


def build_risk_summary(row: pd.Series, scoring: dict) -> str:
    fragments: List[str] = []
    must_include: List[str] = []

    nrr_tier = scoring.get("nrr_tier", "UNKNOWN")
    nrr_display = str(scoring.get("nrr_display", "N/A")).replace("%", "").strip()
    threading_tier = scoring.get("threading_tier", "UNKNOWN")
    contact_count = scoring.get("contact_count")
    expansion_tier = scoring.get("expansion_tier", "LOW")

    # Priority 1: NRR CRITICAL
    if nrr_tier == "CRITICAL":
        fragments.append(f"Revenue is declining at {nrr_display}% NRR")
    # Priority 2: NRR AT_RISK
    elif nrr_tier == "AT_RISK":
        fragments.append(f"NRR is below target at {nrr_display}%")

    # Priority 3: Renewal < 90 days
    renewal_days = _renewal_days(row)
    if renewal_days is not None and renewal_days < 90:
        fragments.append(f"renewal in {renewal_days} days")

    # Priority 4-5: Threading
    if contact_count is not None:
        contact_word = "contact" if contact_count == 1 else "contacts"
        if threading_tier == "SINGLE":
            fragments.append(f"only {contact_count} executive {contact_word} on file")
        elif threading_tier == "DUAL":
            fragments.append(f"only {contact_count} executive {contact_word} \u2014 needs a third")

    # Priority 6: Low health (must-include — P1 hard override trigger)
    health = _parse_health(row)
    if health is not None and health <= 2:
        must_include.append(f"health score is {health:.0f}")

    # Priority 7: Expansion HIGH
    if expansion_tier == "HIGH":
        channel_count = _count_channels(scoring)
        if channel_count > 0:
            fragments.append(f"{channel_count} product channels are uncaptured or competitor-held")

    # Priority 8-9: Positive NRR
    if nrr_tier not in ("CRITICAL", "AT_RISK", "UNKNOWN"):
        if nrr_tier == "STRONG":
            fragments.append(f"Strong growth at {nrr_display}% NRR")
        elif nrr_tier == "HEALTHY":
            fragments.append(f"NRR is stable at {nrr_display}%")

    # Priority 10: Well multi-threaded
    if threading_tier == "MULTI":
        fragments.append("well multi-threaded")

    # Take top 3 + must-includes
    selected = fragments[:3]
    for mi in must_include:
        if mi not in selected:
            selected.append(mi)

    if not selected:
        return "No major risk signals identified."

    return _assemble(selected)


def _assemble(fragments: List[str]) -> str:
    if len(fragments) == 1:
        sentence = fragments[0]
    elif len(fragments) == 2:
        sentence = f"{fragments[0]}, {fragments[1]}"
    else:
        sentence = f"{fragments[0]}, {fragments[1]} \u2014 {fragments[2]}"
        if len(fragments) > 3:
            sentence += ", " + ", ".join(fragments[3:])

    sentence = sentence[0].upper() + sentence[1:]
    if not sentence.endswith("."):
        sentence += "."
    return sentence


def _renewal_days(row: pd.Series):
    try:
        rd = pd.to_datetime(row.get("renewal_date"), errors="coerce")
        if pd.isna(rd):
            return None
        return (rd - pd.Timestamp.now()).days
    except Exception:
        return None


def _parse_health(row: pd.Series):
    raw = row.get("health_score", "")
    try:
        val = float(str(raw).strip())
        if pd.isna(val):
            return None
        return val
    except (ValueError, TypeError):
        return None


def _count_channels(scoring: dict) -> int:
    competitors = scoring.get("competitor_channels", [])
    whitespace = scoring.get("whitespace_channels", [])

    if isinstance(competitors, str):
        try:
            competitors = ast.literal_eval(competitors)
        except Exception:
            competitors = []
    if isinstance(whitespace, str):
        try:
            whitespace = ast.literal_eval(whitespace)
        except Exception:
            whitespace = []

    return len(competitors) + len(whitespace)
