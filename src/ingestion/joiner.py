"""
Join Maps + Tech Stake + Summary tabs into a single master account DataFrame.

Join strategy:
- Summary is the base (left table) — it has the financial data
- Tech Stake is joined on account_name to add product coverage
- Maps is joined on account_name to add AE/territory/contact info
- A 'region' column and 'spreadsheet_id' column are added per row
"""

import logging
from typing import Optional, Dict, List

import pandas as pd

logger = logging.getLogger(__name__)

JOIN_KEY = "account_name"


def join_region_sheets(
    sheets: Dict[str, pd.DataFrame],
    region: str,
    spreadsheet_id: str = "",
) -> pd.DataFrame:
    """
    Join the three tabs for one region into a single flat DataFrame.

    Args:
        sheets: Dict with keys "maps_tab", "tech_stake_tab", "summary_tab".
        region: Region label (e.g., "APAC") — added as a column.
        spreadsheet_id: The source spreadsheet ID — added for write-back routing.

    Returns:
        Joined DataFrame for this region. Empty DF if summary is missing.
    """
    summary = sheets.get("summary_tab", pd.DataFrame())
    tech_stake = sheets.get("tech_stake_tab", pd.DataFrame())
    maps = sheets.get("maps_tab", pd.DataFrame())

    if summary.empty:
        logger.warning("[%s] Summary tab is empty or missing — skipping region.", region)
        return pd.DataFrame()

    if JOIN_KEY not in summary.columns:
        logger.warning(
            "[%s] Summary tab missing '%s' column. Available: %s",
            region, JOIN_KEY, list(summary.columns),
        )
        return pd.DataFrame()

    # Normalize join key: strip whitespace, lowercase for matching
    summary = summary.copy()
    summary[JOIN_KEY] = summary[JOIN_KEY].astype(str).str.strip()
    summary = summary[summary[JOIN_KEY].str.len() > 0]

    result = summary.copy()

    # Join Tech Stake
    if not tech_stake.empty and JOIN_KEY in tech_stake.columns:
        tech_stake = tech_stake.copy()
        tech_stake[JOIN_KEY] = tech_stake[JOIN_KEY].astype(str).str.strip()
        # Drop columns that already exist in summary (except join key)
        ts_cols = [JOIN_KEY] + [c for c in tech_stake.columns if c != JOIN_KEY and c not in result.columns]
        result = result.merge(
            tech_stake[ts_cols], on=JOIN_KEY, how="left", suffixes=("", "_ts")
        )
        logger.info("[%s] Joined Tech Stake: %d columns added", region, len(ts_cols) - 1)
    else:
        logger.warning("[%s] Tech Stake tab missing or has no account_name column.", region)

    # Join Maps
    if not maps.empty and JOIN_KEY in maps.columns:
        maps = maps.copy()
        maps[JOIN_KEY] = maps[JOIN_KEY].astype(str).str.strip()
        maps_cols = [JOIN_KEY] + [c for c in maps.columns if c != JOIN_KEY and c not in result.columns]
        result = result.merge(
            maps[maps_cols], on=JOIN_KEY, how="left", suffixes=("", "_maps")
        )
        logger.info("[%s] Joined Maps: %d columns added", region, len(maps_cols) - 1)
    else:
        logger.warning("[%s] Maps tab missing or has no account_name column.", region)

    # Add metadata columns
    result["region"] = region
    result["spreadsheet_id"] = spreadsheet_id

    logger.info(
        "[%s] Joined result: %d accounts × %d columns", region, len(result), len(result.columns)
    )
    return result


def join_all_regions(
    region_data: Dict[str, Dict[str, pd.DataFrame]],
    regional_ids: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    Concatenate per-region master DataFrames into one global DataFrame.

    Args:
        region_data: {region: {sheet_type: DataFrame}} from loader.load_all_regions().
        regional_ids: {region: spreadsheet_id} for write-back routing.

    Returns:
        Global master DataFrame with all accounts, reset index.
    """
    regional_dfs: List[pd.DataFrame] = []
    for region, sheets in region_data.items():
        spreadsheet_id = (regional_ids or {}).get(region, "")
        df = join_region_sheets(sheets, region, spreadsheet_id)
        if not df.empty:
            regional_dfs.append(df)

    if not regional_dfs:
        logger.error("No regional DataFrames produced — master DataFrame is empty.")
        return pd.DataFrame()

    master = pd.concat(regional_dfs, ignore_index=True, sort=False)
    n_regions = master["region"].nunique() if "region" in master.columns else 0
    logger.info("Master DataFrame: %d total accounts across %d region(s)", len(master), n_regions)
    return master


def get_account_key(row: pd.Series) -> str:
    """Return a unique composite key for an account row.

    Format: 'REGION::AccountName::AE_Name'
    The AE name is included because Maps-tab joins can produce multiple rows
    for the same account (different AEs/territories), each needing its own
    comment.  If ae_name is missing or empty, falls back to 'REGION::AccountName'.
    """
    region = row.get("region", "UNKNOWN")
    account = row.get("account_name", "UNKNOWN")
    ae = str(row.get("ae_name", "") or "").strip()
    if ae and ae.lower() not in ("nan", "n/a", "none", ""):
        return f"{region}::{account}::{ae}"
    return f"{region}::{account}"
