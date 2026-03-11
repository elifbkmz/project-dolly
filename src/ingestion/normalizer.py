"""
Column name normalization.

Resolves regional column name drift using a YAML mapping file.
Channel columns in the Tech Stake tab are matched using fuzzy string matching
(difflib.SequenceMatcher) to handle minor naming variations.
"""

import logging
from difflib import SequenceMatcher
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def normalize_columns(
    df: pd.DataFrame,
    sheet_type: str,
    mapping: dict,
    region: str = "",
) -> pd.DataFrame:
    """
    Rename DataFrame columns to canonical names using the YAML mapping.

    Args:
        df: Raw DataFrame from Google Sheets.
        sheet_type: One of "maps_tab", "tech_stake_tab", "summary_tab".
        mapping: Loaded column_mappings.yaml content.
        region: Region label (used in log messages only).

    Returns:
        DataFrame with renamed columns. Unmapped columns are preserved as-is.
    """
    if df.empty:
        return df

    tab_mapping = mapping.get(sheet_type, {})
    rename_map: dict[str, str] = {}
    corrections = 0

    # Build a flat {alias_lower → canonical} lookup
    alias_to_canonical: dict[str, str] = {}
    for canonical, aliases in tab_mapping.items():
        if canonical == "channels":
            continue  # handled separately
        if isinstance(aliases, list):
            for alias in aliases:
                alias_to_canonical[alias.lower().strip()] = canonical

    for col in df.columns:
        col_clean = str(col).lower().strip()
        # 1. Exact match
        if col_clean in alias_to_canonical:
            canonical = alias_to_canonical[col_clean]
            if canonical != col:
                rename_map[col] = canonical
                corrections += 1
                logger.debug("[%s/%s] Column '%s' → '%s'", region, sheet_type, col, canonical)
            continue
        # 2. "Starts-with" match: handles long column headers where the cell
        #    text begins with a known alias followed by newlines/extra instructions.
        #    e.g. actual header: "Next Steps & Execution Strategy\n\nIf you could..."
        #    alias: "next steps & execution strategy"
        for alias, canonical in alias_to_canonical.items():
            if len(alias) >= 8 and col_clean.startswith(alias):
                if canonical != col:
                    rename_map[col] = canonical
                    corrections += 1
                    logger.debug(
                        "[%s/%s] Column '%s' → '%s' (starts-with match)",
                        region, sheet_type, col, canonical,
                    )
                break

    if rename_map:
        df = df.rename(columns=rename_map)
        logger.info(
            "[%s] %s: %d column(s) normalized", region, sheet_type, corrections
        )

    # Deduplicate column names: if two columns end up with the same name,
    # keep the first and suffix the rest with _dup_N to avoid pandas Series issues.
    seen: dict = {}
    new_cols = []
    for col in df.columns:
        if col in seen:
            seen[col] += 1
            new_cols.append(f"{col}_dup_{seen[col]}")
        else:
            seen[col] = 0
            new_cols.append(col)
    if new_cols != list(df.columns):
        df.columns = new_cols
        logger.debug("[%s/%s] Deduplicated column names", region, sheet_type)

    return df


def resolve_channel_columns(
    df: pd.DataFrame,
    channel_config: dict,
    fuzzy_threshold: float = 0.75,
) -> pd.DataFrame:
    """
    Normalize Tech Stake channel columns using fuzzy matching.

    Matches existing DataFrame columns against all known channel aliases.
    Any column with a SequenceMatcher ratio >= fuzzy_threshold to a known alias
    is renamed to the canonical channel name.

    Args:
        df: Tech Stake DataFrame (already through normalize_columns).
        channel_config: The "channels" sub-dict from column_mappings.yaml.
        fuzzy_threshold: Minimum similarity ratio (default 0.75).

    Returns:
        DataFrame with channel columns renamed to canonical names.
    """
    if df.empty or not channel_config:
        return df

    # Build a flat {alias_lower → canonical} map for all channel aliases
    channel_alias_map: dict[str, str] = {}
    for canonical, aliases in channel_config.items():
        if isinstance(aliases, list):
            for alias in aliases:
                channel_alias_map[alias.lower().strip()] = canonical

    rename_map: dict[str, str] = {}
    for col in df.columns:
        col_clean = str(col).lower().strip()
        # Skip columns already matched to canonical names
        if col_clean in channel_alias_map.values():
            continue
        # Exact match first
        if col_clean in channel_alias_map:
            canonical = channel_alias_map[col_clean]
            if canonical != col:
                rename_map[col] = canonical
            continue
        # Fuzzy match
        best_ratio = 0.0
        best_canonical: Optional[str] = None
        for alias, canonical in channel_alias_map.items():
            ratio = SequenceMatcher(None, col_clean, alias).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_canonical = canonical
        if best_ratio >= fuzzy_threshold and best_canonical and best_canonical != col:
            rename_map[col] = best_canonical
            logger.debug(
                "Fuzzy match: '%s' → '%s' (ratio=%.2f)", col, best_canonical, best_ratio
            )

    if rename_map:
        df = df.rename(columns=rename_map)
        logger.info("Channel columns normalized: %d renames applied", len(rename_map))

    # Deduplicate after channel renaming
    seen: dict = {}
    new_cols = []
    for col in df.columns:
        if col in seen:
            seen[col] += 1
            new_cols.append(f"{col}_dup_{seen[col]}")
        else:
            seen[col] = 0
            new_cols.append(col)
    if new_cols != list(df.columns):
        df.columns = new_cols

    return df


def audit_normalization(
    original_cols: list[str],
    normalized_cols: list[str],
    region: str,
    sheet_type: str,
) -> dict:
    """
    Compare original vs. normalized column lists and return an audit report.

    Returns:
        Dict with: mapped (list), unchanged (list), stats (dict).
    """
    mapped = [
        {"original": o, "canonical": n}
        for o, n in zip(original_cols, normalized_cols)
        if o != n
    ]
    unchanged = [o for o, n in zip(original_cols, normalized_cols) if o == n]
    return {
        "region": region,
        "sheet_type": sheet_type,
        "mapped_count": len(mapped),
        "unchanged_count": len(unchanged),
        "mappings": mapped,
    }
