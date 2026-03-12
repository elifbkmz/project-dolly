"""Tests for the deterministic risk summary generator."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import pytest
from ui.components.risk_summary import build_risk_summary


def _make_row(**overrides):
    defaults = {
        "account_name": "Test Corp", "region": "APAC",
        "ae_name": "Jane Doe", "renewal_date": "2027-01-01", "health_score": "5",
    }
    defaults.update(overrides)
    return pd.Series(defaults)


def _make_scoring(**overrides):
    defaults = {
        "nrr_tier": "HEALTHY", "nrr_display": "102%",
        "threading_tier": "MULTI", "contact_count": 4,
        "expansion_tier": "LOW", "competitor_channels": [],
        "whitespace_channels": [], "attention_tier": "P3",
    }
    defaults.update(overrides)
    return defaults


class TestBuildRiskSummary:
    def test_p1_critical_nrr_single_threaded(self):
        row = _make_row(renewal_date="2026-04-01")
        scoring = _make_scoring(
            nrr_tier="CRITICAL", nrr_display="84%",
            threading_tier="SINGLE", contact_count=1, attention_tier="P1",
        )
        result = build_risk_summary(row, scoring)
        assert "84%" in result
        assert "1 executive contact" in result
        assert result.endswith(".")

    def test_p2_at_risk_with_expansion(self):
        scoring = _make_scoring(
            nrr_tier="AT_RISK", nrr_display="94%",
            threading_tier="DUAL", contact_count=2, expansion_tier="HIGH",
            competitor_channels=[{"channel": "CDP", "vendor": "Segment"}],
            whitespace_channels=["SMS", "WhatsApp", "Email"], attention_tier="P2",
        )
        result = build_risk_summary(_make_row(), scoring)
        assert "94%" in result
        assert "4 product channels" in result

    def test_p3_strong_healthy(self):
        scoring = _make_scoring(
            nrr_tier="STRONG", nrr_display="118%",
            threading_tier="MULTI", contact_count=5, attention_tier="P3",
        )
        result = build_risk_summary(_make_row(), scoring)
        assert "118%" in result
        assert "multi-threaded" in result

    def test_no_signals_returns_default(self):
        scoring = _make_scoring(
            nrr_tier="UNKNOWN", threading_tier="UNKNOWN", expansion_tier="LOW",
        )
        result = build_risk_summary(_make_row(), scoring)
        assert result == "No major risk signals identified."

    def test_low_health_always_included(self):
        row = _make_row(health_score="1")
        scoring = _make_scoring(
            nrr_tier="CRITICAL", nrr_display="80%",
            threading_tier="SINGLE", contact_count=1, attention_tier="P1",
        )
        result = build_risk_summary(row, scoring)
        assert "health" in result.lower()

    def test_renewal_under_90_days(self):
        future = (pd.Timestamp.now() + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
        row = _make_row(renewal_date=future)
        scoring = _make_scoring(
            nrr_tier="AT_RISK", nrr_display="91%", attention_tier="P2",
        )
        result = build_risk_summary(row, scoring)
        assert "renewal" in result.lower()

    def test_contact_count_none_skips_threading(self):
        scoring = _make_scoring(
            nrr_tier="AT_RISK", nrr_display="92%",
            threading_tier="SINGLE", contact_count=None, attention_tier="P2",
        )
        result = build_risk_summary(_make_row(), scoring)
        assert "contact" not in result.lower()

    def test_string_channel_lists_handled(self):
        scoring = _make_scoring(
            nrr_tier="AT_RISK", nrr_display="93%", expansion_tier="HIGH",
            competitor_channels="[{'channel': 'CDP', 'vendor': 'Segment'}]",
            whitespace_channels="['SMS', 'WhatsApp']", attention_tier="P2",
        )
        result = build_risk_summary(_make_row(), scoring)
        assert "3 product channels" in result

    def test_result_ends_with_period(self):
        scoring = _make_scoring(nrr_tier="STRONG", nrr_display="115%")
        result = build_risk_summary(_make_row(), scoring)
        assert result.endswith(".")
