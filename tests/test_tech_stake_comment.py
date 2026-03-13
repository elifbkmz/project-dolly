"""Tests for tech-stake comment generation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import pytest
from src.llm.tech_stake_comment import detect_vendor_gaps, filter_accounts_with_gaps


# ── Sample data helpers ──────────────────────────────────────────────────────

def _row_with_competitors() -> pd.Series:
    """Account with 2 competitor gaps and 3 whitespace gaps."""
    return pd.Series({
        "account_name": "Acme Corp",
        "region": "EMEA",
        "arr": "$50,000",
        "competitor_channels": [
            {"channel": "Smart Recommender", "vendor": "Algolia"},
            {"channel": "Customer Support Chatbot", "vendor": "Zendesk"},
        ],
        "whitespace_channels": ["Eureka Search", "Shopping Agent", "Gamification"],
    })


def _row_no_gaps() -> pd.Series:
    """Account with no competitor or whitespace gaps."""
    return pd.Series({
        "account_name": "Beta Inc",
        "region": "EMEA",
        "arr": "$30,000",
        "competitor_channels": [],
        "whitespace_channels": [],
    })


def _sample_scored_df() -> pd.DataFrame:
    """3-account DataFrame: Acme has gaps, Beta has none, Gamma has gaps."""
    return pd.DataFrame([
        {
            "account_name": "Acme Corp",
            "region": "EMEA",
            "arr": "$50,000",
            "competitor_channels": [
                {"channel": "Smart Recommender", "vendor": "Algolia"},
                {"channel": "Customer Support Chatbot", "vendor": "Zendesk"},
            ],
            "whitespace_channels": ["Eureka Search", "Shopping Agent", "Gamification"],
        },
        {
            "account_name": "Beta Inc",
            "region": "EMEA",
            "arr": "$30,000",
            "competitor_channels": [],
            "whitespace_channels": [],
        },
        {
            "account_name": "Gamma LLC",
            "region": "EMEA",
            "arr": "$80,000",
            "competitor_channels": [
                {"channel": "CDP", "vendor": "Segment"},
            ],
            "whitespace_channels": ["SMS"],
        },
    ])


# ── Tests: detect_vendor_gaps ────────────────────────────────────────────────

class TestDetectVendorGapsCompetitors:
    """Competitor gap detection."""

    def test_detect_vendor_gaps_competitors(self):
        """2 competitor gaps found, Algolia and Zendesk present."""
        row = _row_with_competitors()
        result = detect_vendor_gaps(row)
        assert len(result["competitor_gaps"]) == 2
        joined = " ".join(result["competitor_gaps"])
        assert "Algolia" in joined
        assert "Zendesk" in joined


class TestDetectVendorGapsWhitespace:
    """Whitespace gap detection."""

    def test_detect_vendor_gaps_whitespace(self):
        """3 whitespace gaps, Eureka Search present."""
        row = _row_with_competitors()
        result = detect_vendor_gaps(row)
        assert len(result["whitespace_gaps"]) == 3
        assert "Eureka Search" in result["whitespace_gaps"]


class TestDetectVendorGapsHasGaps:
    """has_gaps flag when gaps exist."""

    def test_detect_vendor_gaps_has_gaps(self):
        """True when gaps exist."""
        row = _row_with_competitors()
        result = detect_vendor_gaps(row)
        assert result["has_gaps"] is True


class TestDetectVendorGapsNoGaps:
    """has_gaps flag when no gaps exist."""

    def test_detect_vendor_gaps_no_gaps(self):
        """False when both lists empty."""
        row = _row_no_gaps()
        result = detect_vendor_gaps(row)
        assert result["has_gaps"] is False
        assert result["gap_count"] == 0


class TestFilterAccountsWithGaps:
    """Filtering and sorting logic."""

    def test_filter_accounts_with_gaps(self):
        """Filters to 2 of 3 accounts, sorted by ARR desc (Gamma 80K first, Acme 50K second)."""
        df = _sample_scored_df()
        result = filter_accounts_with_gaps(df, min_arr=5000)
        assert len(result) == 2
        assert result.iloc[0]["account_name"] == "Gamma LLC"
        assert result.iloc[1]["account_name"] == "Acme Corp"
