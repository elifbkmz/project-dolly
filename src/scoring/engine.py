"""
Scoring pipeline orchestrator.

Entry point for running the full scoring pipeline over a master DataFrame.
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

from src.scoring.composite import score_all_accounts
from src.utils.config_loader import load_scoring_weights, load_column_mappings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent


def run_scoring_pipeline(
    master_df: pd.DataFrame,
    scoring_weights_config: Optional[dict] = None,
    column_mapping: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Run the full scoring pipeline over the master account DataFrame.

    Args:
        master_df: Global joined DataFrame from joiner.join_all_regions().
        scoring_weights_config: Loaded scoring_weights.yaml (auto-loaded if None).
        column_mapping: Loaded column_mappings.yaml (auto-loaded if None).

    Returns:
        Scored and sorted DataFrame with all scoring columns + rank column.
    """
    if master_df.empty:
        logger.warning("Scoring pipeline received an empty DataFrame.")
        return master_df

    if scoring_weights_config is None:
        scoring_weights_config = load_scoring_weights()
    if column_mapping is None:
        column_mapping = load_column_mappings()

    weights = scoring_weights_config.get("weights", {})
    composite_thresholds = scoring_weights_config.get("composite_tiers", {})
    composite_thresholds["renewal_days_p1"] = composite_thresholds.get(
        "renewal_days_p1",
        scoring_weights_config.get("composite_tiers", {}).get("renewal_days_p1", 90),
    )

    logger.info("Running scoring pipeline on %d accounts...", len(master_df))

    scored_df = score_all_accounts(
        master_df,
        weights=weights,
        thresholds=composite_thresholds,
        scoring_weights_config=scoring_weights_config,
        column_mapping=column_mapping,
    )

    return scored_df


def save_scored_df(scored_df: pd.DataFrame, output_path: str = "data/processed/master_scored.csv") -> Path:
    """Save the scored DataFrame to CSV for caching between sessions."""
    resolved = PROJECT_ROOT / output_path
    resolved.parent.mkdir(parents=True, exist_ok=True)
    scored_df.to_csv(resolved, index=False)
    logger.info("Scored DataFrame saved to: %s (%d rows)", resolved, len(scored_df))
    return resolved


def load_scored_df(path: str = "data/processed/master_scored.csv") -> pd.DataFrame:
    """Load a previously scored DataFrame from CSV."""
    resolved = PROJECT_ROOT / path
    if not resolved.exists():
        raise FileNotFoundError(f"Scored DataFrame not found at: {resolved}")
    df = pd.read_csv(resolved, low_memory=False)
    logger.info("Loaded scored DataFrame from: %s (%d rows)", resolved, len(df))
    return df
