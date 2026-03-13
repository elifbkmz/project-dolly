"""Tests for portfolio-level comment generation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import pytest
from src.llm.portfolio_comment import aggregate_portfolio_metrics


def _sample_scored_df() -> pd.DataFrame:
    """Return a 3-row scored DataFrame for testing."""
    future_30 = (pd.Timestamp.now() + pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    return pd.DataFrame([
        {
            "account_name": "Acme Corp",
            "region": "EMEA",
            "attention_tier": "P1",
            "nrr_tier": "CRITICAL",
            "nrr_display": "82%",
            "arr": "$50,000",
            "composite_score": 85.0,
            "primary_signal": "NRR CRITICAL (82%)",
            "renewal_date": future_30,
            "competitor_channels": "[{'channel': 'CDP', 'vendor': 'Segment'}]",
            "whitespace_channels": "['SMS', 'WhatsApp']",
        },
        {
            "account_name": "Beta Inc",
            "region": "EMEA",
            "attention_tier": "P3",
            "nrr_tier": "HEALTHY",
            "nrr_display": "105%",
            "arr": "$30,000",
            "composite_score": 35.0,
            "primary_signal": "On track",
            "renewal_date": "2027-06-01",
            "competitor_channels": "[]",
            "whitespace_channels": "[]",
        },
        {
            "account_name": "Gamma LLC",
            "region": "EMEA",
            "attention_tier": "P2",
            "nrr_tier": "AT_RISK",
            "nrr_display": "93%",
            "arr": "$80,000",
            "composite_score": 60.0,
            "primary_signal": "NRR AT RISK (93%)",
            "renewal_date": "2027-03-15",
            "competitor_channels": "[{'channel': 'Email', 'vendor': 'Mailchimp'}]",
            "whitespace_channels": "['Push', 'In-App']",
        },
    ])


class TestAggregatePortfolioMetricsCounts:
    """Test P1/P2/P3 tier counts."""

    def test_p1_count(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        assert metrics["p1_count"] == 1

    def test_p2_count(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        assert metrics["p2_count"] == 1

    def test_p3_count(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        assert metrics["p3_count"] == 1

    def test_total_accounts(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        assert metrics["total_accounts"] == 3


class TestAggregatePortfolioMetricsArr:
    """Test total ARR formatting."""

    def test_total_arr_is_dollar_formatted(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        # 50000 + 30000 + 80000 = 160000
        assert metrics["total_arr"] == "$160,000"

    def test_handles_numeric_arr(self):
        df = _sample_scored_df()
        df["arr"] = [50000, 30000, 80000]
        metrics = aggregate_portfolio_metrics(df)
        assert metrics["total_arr"] == "$160,000"


class TestAggregatePortfolioMetricsNrrDistribution:
    """Test NRR tier distribution counts."""

    def test_critical_count(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        assert metrics["nrr_critical_count"] == 1

    def test_at_risk_count(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        assert metrics["nrr_at_risk_count"] == 1

    def test_healthy_count(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        assert metrics["nrr_healthy_count"] == 1

    def test_strong_count(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        assert metrics["nrr_strong_count"] == 0


class TestAggregatePortfolioMetricsTop5:
    """Test top accounts by composite score."""

    def test_top_accounts_contains_highest_scorer(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        assert "Acme Corp" in metrics["top_5_accounts"]

    def test_top_accounts_contains_all_three(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        for name in ["Acme Corp", "Beta Inc", "Gamma LLC"]:
            assert name in metrics["top_5_accounts"]

    def test_top_accounts_order(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        # Acme (85) should appear before Gamma (60) which should appear before Beta (35)
        acme_pos = metrics["top_5_accounts"].index("Acme Corp")
        gamma_pos = metrics["top_5_accounts"].index("Gamma LLC")
        beta_pos = metrics["top_5_accounts"].index("Beta Inc")
        assert acme_pos < gamma_pos < beta_pos


class TestAggregatePortfolioMetricsOpportunities:
    """Test competitor and whitespace opportunity counts."""

    def test_competitor_opportunity_count(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        # Acme Corp and Gamma LLC have non-empty competitor_channels
        assert metrics["competitor_opportunity_count"] == 2

    def test_whitespace_opportunity_count(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        # Acme Corp and Gamma LLC have non-empty whitespace_channels
        assert metrics["whitespace_opportunity_count"] == 2

    def test_displacement_count(self):
        metrics = aggregate_portfolio_metrics(_sample_scored_df())
        # Displacement = accounts that have EITHER competitor or whitespace
        assert metrics["displacement_count"] == 2
