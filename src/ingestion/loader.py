"""
Ingestion orchestrator.

Coordinates:
1. Google Drive file discovery
2. Per-region Sheets tab loading
3. Sheet type auto-detection
4. Column normalization
"""

import logging
from typing import Optional, Dict

import pandas as pd

from src.google.drive_client import discover_regional_files
from src.google.sheets_client import detect_sheet_names, read_sheet_as_dataframe
from src.ingestion.normalizer import normalize_columns, resolve_channel_columns
from src.utils.config_loader import load_column_mappings, load_regions_config

logger = logging.getLogger(__name__)


def detect_sheet_type(sheet_name: str, keywords: dict) -> Optional[str]:
    """
    Identify a tab as 'maps_tab', 'tech_stake_tab', or 'summary_tab'
    by checking if the tab name contains any of the registered keywords.

    Args:
        sheet_name: The tab name from the spreadsheet.
        keywords: sheet_type_keywords from regions.yaml.

    Returns:
        One of "maps_tab", "tech_stake_tab", "summary_tab", or None.
    """
    name_lower = sheet_name.lower()
    # Map our internal type names to the YAML type keys
    type_map = {
        "maps": "maps_tab",
        "tech_stake": "tech_stake_tab",
        "summary": "summary_tab",
    }
    for yaml_key, internal_type in type_map.items():
        for kw in keywords.get(yaml_key, []):
            if kw.lower() in name_lower:
                return internal_type
    return None


def load_region_from_sheets(
    sheets_service,
    spreadsheet_id: str,
    region: str,
    regions_config: dict,
    column_mapping: dict,
) -> Dict[str, pd.DataFrame]:
    """
    Load and normalize all tabs for a single regional spreadsheet.

    Args:
        sheets_service: Authenticated Sheets API service.
        spreadsheet_id: Google Sheets ID for this region.
        region: Region label (e.g., "APAC").
        regions_config: Loaded regions.yaml config.
        column_mapping: Loaded column_mappings.yaml config.

    Returns:
        Dict with up to 3 keys: "maps_tab", "tech_stake_tab", "summary_tab".
        Each value is a normalized DataFrame (empty DF if tab not found).
    """
    tab_names = detect_sheet_names(sheets_service, spreadsheet_id)
    keywords = regions_config.get("sheet_type_keywords", {})
    explicit = regions_config.get("explicit_sheet_names", {})
    channel_config = column_mapping.get("tech_stake_tab", {}).get("channels", {})

    found_tabs: Dict[str, str] = {}  # {internal_type → actual_tab_name}

    # First pass: explicit overrides
    for yaml_key, internal_type in [("maps", "maps_tab"), ("tech_stake", "tech_stake_tab"), ("summary", "summary_tab")]:
        explicit_name = explicit.get(yaml_key) if explicit else None
        if explicit_name and explicit_name in tab_names:
            found_tabs[internal_type] = explicit_name

    # Second pass: auto-detect remaining types
    for tab_name in tab_names:
        detected = detect_sheet_type(tab_name, keywords)
        if detected and detected not in found_tabs:
            found_tabs[detected] = tab_name

    if not found_tabs:
        logger.warning(
            "[%s] No recognizable tabs found in spreadsheet %s. Available: %s",
            region, spreadsheet_id, tab_names,
        )

    result: Dict[str, pd.DataFrame] = {}
    for sheet_type, tab_name in found_tabs.items():
        logger.info("[%s] Loading tab '%s' as %s", region, tab_name, sheet_type)
        df = read_sheet_as_dataframe(sheets_service, spreadsheet_id, tab_name)
        original_cols = list(df.columns)
        df = normalize_columns(df, sheet_type, column_mapping, region)
        if sheet_type == "tech_stake_tab":
            df = resolve_channel_columns(df, channel_config)
        result[sheet_type] = df
        logger.debug(
            "[%s/%s] Normalized columns: %s", region, sheet_type, list(df.columns)
        )

    return result


def load_all_regions(
    drive_service,
    sheets_service,
    regions_config: Optional[dict] = None,
    column_mapping: Optional[dict] = None,
) -> Dict[str, Dict[str, pd.DataFrame]]:
    """
    Orchestrate Drive discovery and Sheets loading for all configured regions.

    Args:
        drive_service: Authenticated Drive API service.
        sheets_service: Authenticated Sheets API service.
        regions_config: Loaded regions.yaml (auto-loaded if None).
        column_mapping: Loaded column_mappings.yaml (auto-loaded if None).

    Returns:
        Dict: {region_name: {sheet_type: DataFrame}}
    """
    if regions_config is None:
        regions_config = load_regions_config()
    if column_mapping is None:
        column_mapping = load_column_mappings()

    drive_config = regions_config.get("drive", {})
    folder_id = drive_config.get("shared_folder_id", "")
    pattern_map = drive_config.get("file_pattern_map", {})

    if not folder_id or folder_id == "REPLACE_WITH_YOUR_DRIVE_FOLDER_ID":
        raise ValueError(
            "Drive folder ID not configured. "
            "Set 'drive.shared_folder_id' in config/regions.yaml."
        )

    # Discover files
    regional_ids = discover_regional_files(drive_service, folder_id, pattern_map)
    if not regional_ids:
        raise ValueError(
            f"No regional files found in Drive folder '{folder_id}'. "
            "Check that the service account has access and the folder ID is correct."
        )

    # Load each region
    all_data: Dict[str, Dict[str, pd.DataFrame]] = {}
    for region, spreadsheet_id in regional_ids.items():
        logger.info("Loading region: %s (spreadsheet: %s)", region, spreadsheet_id)
        try:
            all_data[region] = load_region_from_sheets(
                sheets_service, spreadsheet_id, region, regions_config, column_mapping
            )
        except Exception as exc:
            logger.error("[%s] Failed to load: %s", region, exc)
            all_data[region] = {}

    return all_data
