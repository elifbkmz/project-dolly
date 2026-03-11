"""
Data quality validation for the master account DataFrame.
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["account_name", "region"]
IMPORTANT_COLUMNS = ["arr", "nrr", "renewal_date", "ae_name"]


def validate_master_df(df: pd.DataFrame) -> list[str]:
    """
    Run quality checks on the joined master DataFrame.

    Args:
        df: The global master DataFrame after joining all regions.

    Returns:
        List of warning strings. Empty list means no issues found.
    """
    warnings: list[str] = []

    if df.empty:
        warnings.append("CRITICAL: Master DataFrame is empty — no accounts loaded.")
        return warnings

    # Required columns
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            warnings.append(f"CRITICAL: Required column '{col}' is missing.")

    # Important columns (soft warning)
    for col in IMPORTANT_COLUMNS:
        if col not in df.columns:
            warnings.append(f"WARNING: Important column '{col}' is missing — scoring may be degraded.")
        else:
            null_pct = df[col].isna().mean() * 100
            if null_pct > 30:
                warnings.append(
                    f"WARNING: Column '{col}' is {null_pct:.0f}% null — "
                    "many accounts will use fallback scores."
                )

    # Duplicate account_names within a region
    if "account_name" in df.columns and "region" in df.columns:
        dupes = df[df.duplicated(subset=["account_name", "region"], keep=False)]
        if not dupes.empty:
            warnings.append(
                f"WARNING: {len(dupes)} rows have duplicate account_name within the same region. "
                "Check: " + ", ".join(
                    f"{r}/{n}" for r, n in dupes[["region", "account_name"]].drop_duplicates().values
                )[:200]
            )

    # Row count
    logger.info("Master DataFrame: %d accounts across %d region(s)", len(df), df["region"].nunique() if "region" in df.columns else 0)

    return warnings
