"""
Google Drive client for discovering regional account planning files.

Uses the Drive API to list files in a shared folder and match them
to regions using filename patterns (fnmatch syntax).
"""

import fnmatch
import logging
from typing import Optional, List, Dict

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account

logger = logging.getLogger(__name__)


def build_drive_service(credentials: service_account.Credentials):
    """Build and return a Google Drive API service object."""
    return build("drive", "v3", credentials=credentials)


def list_sheets_in_folder(drive_service, folder_id: str, recurse: bool = True) -> List[dict]:
    """
    Lists all Google Sheets files in a Drive folder, optionally recursing into subfolders.

    Args:
        drive_service: Authenticated Drive API service.
        folder_id: Google Drive folder ID (from the folder URL).
        recurse: If True, also scan subfolders (and their subfolders).

    Returns:
        List of dicts with keys: id, name, modifiedTime.

    Raises:
        HttpError: If the folder is not accessible (wrong ID or no permission).
    """
    try:
        # Get spreadsheets in this folder
        sheets_query = (
            f"'{folder_id}' in parents "
            "and mimeType='application/vnd.google-apps.spreadsheet' "
            "and trashed=false"
        )
        response = (
            drive_service.files()
            .list(q=sheets_query, fields="files(id, name, modifiedTime)", orderBy="name", pageSize=100)
            .execute()
        )
        files = list(response.get("files", []))

        if recurse:
            # Find subfolders and recurse
            folder_query = (
                f"'{folder_id}' in parents "
                "and mimeType='application/vnd.google-apps.folder' "
                "and trashed=false"
            )
            folder_resp = (
                drive_service.files()
                .list(q=folder_query, fields="files(id, name)", pageSize=100)
                .execute()
            )
            for subfolder in folder_resp.get("files", []):
                sub_files = list_sheets_in_folder(drive_service, subfolder["id"], recurse=True)
                files.extend(sub_files)

        logger.info("Found %d spreadsheet(s) in folder %s (recurse=%s)", len(files), folder_id, recurse)
        return files
    except HttpError as exc:
        raise HttpError(
            resp=exc.resp,
            content=exc.content,
            uri=f"Drive folder listing for folder_id={folder_id}",
        ) from exc


def discover_regional_files(
    drive_service,
    folder_id: str,
    pattern_map: Dict[str, str],
) -> Dict[str, str]:
    """
    Discovers regional spreadsheet IDs from a Drive folder.

    Supports two folder structures:
    1. **Subfolder-based** (preferred): Each subfolder is a region, and every
       spreadsheet inside it (recursively) is mapped as "Region/AE Name".
    2. **Flat**: All spreadsheets in one folder, matched by filename patterns.

    If the root folder contains subfolders, subfolder-based discovery is used
    and pattern_map is ignored. Otherwise, falls back to pattern matching or
    auto-discovery.

    Args:
        drive_service: Authenticated Drive API service.
        folder_id: Google Drive folder ID.
        pattern_map: Dict mapping region name to fnmatch pattern (flat mode).

    Returns:
        Dict mapping region/AE label to spreadsheet ID.
    """
    try:
        # Check for subfolders first
        folder_query = (
            f"'{folder_id}' in parents "
            "and mimeType='application/vnd.google-apps.folder' "
            "and trashed=false"
        )
        folder_resp = (
            drive_service.files()
            .list(q=folder_query, fields="files(id, name)", orderBy="name", pageSize=100)
            .execute()
        )
        subfolders = folder_resp.get("files", [])
    except HttpError as exc:
        raise HttpError(resp=exc.resp, content=exc.content, uri=f"folder listing {folder_id}") from exc

    result: Dict[str, str] = {}

    # ── Subfolder-based discovery ──
    if subfolders:
        for subfolder in subfolders:
            region_name = subfolder["name"]
            sheets = list_sheets_in_folder(drive_service, subfolder["id"], recurse=True)
            for sheet in sheets:
                label = f"{region_name}/{_filename_to_region(sheet['name'])}"
                result[label] = sheet["id"]
                logger.info("Region '%s' → '%s' (id: %s)", label, sheet["name"], sheet["id"])

        # Also pick up any spreadsheets directly in the root folder
        root_sheets = list_sheets_in_folder(drive_service, folder_id, recurse=False)
        for sheet in root_sheets:
            label = _filename_to_region(sheet["name"])
            result[label] = sheet["id"]
            logger.info("Root sheet '%s' → '%s' (id: %s)", label, sheet["name"], sheet["id"])

        if result:
            logger.info("Discovered %d spreadsheet(s) across %d region subfolder(s)", len(result), len(subfolders))
            return result

    # ── Flat folder: pattern matching or auto-discovery ──
    files = list_sheets_in_folder(drive_service, folder_id, recurse=False)

    if not files:
        raise ValueError(
            f"No Google Sheets files found in Drive folder '{folder_id}'. "
            "Check that the service account has Viewer access to the folder."
        )

    if pattern_map:
        for region, pattern in pattern_map.items():
            matches = [f for f in files if fnmatch.fnmatch(f["name"], pattern)]
            if not matches:
                logger.warning("No file for region '%s' pattern '%s'", region, pattern)
                continue
            if len(matches) > 1:
                logger.warning("Multiple matches for '%s': %s — using first.", region, [m["name"] for m in matches])
            chosen = matches[0]
            result[region] = chosen["id"]
            logger.info("Region '%s' → '%s' (id: %s)", region, chosen["name"], chosen["id"])

    if not result:
        logger.warning("Auto-discovering all %d file(s) as regions.", len(files))
        for f in files:
            region_key = _filename_to_region(f["name"])
            result[region_key] = f["id"]
            logger.info("Auto-region '%s' → '%s' (id: %s)", region_key, f["name"], f["id"])

    return result


def _filename_to_region(filename: str) -> str:
    """
    Convert a filename to a short region/label key.
    Strips common suffixes like 'Master Account Planning - December 2025'.
    Example: 'Copy of Nikhil Venugopal Master Account Planning - December 2025'
             → 'Nikhil Venugopal'
    """
    name = filename
    # Remove leading "Copy of "
    if name.lower().startswith("copy of "):
        name = name[8:]
    # Truncate at common planning doc keywords
    for marker in [" Master Account", " Account Planning", " - December", " - January",
                   " - February", " - March", " - April", " - May", " - June",
                   " - July", " - August", " - September", " - October", " - November"]:
        idx = name.find(marker)
        if idx > 0:
            name = name[:idx]
            break
    # Clean trailing separators
    name = name.strip().rstrip("-").strip()
    return name or filename


def get_file_metadata(drive_service, file_id: str) -> dict:
    """
    Returns metadata for a specific file (name, modifiedTime, etc.).

    Args:
        drive_service: Authenticated Drive API service.
        file_id: Google Drive file ID.

    Returns:
        Dict with file metadata.
    """
    try:
        return (
            drive_service.files()
            .get(fileId=file_id, fields="id, name, modifiedTime")
            .execute()
        )
    except HttpError as exc:
        raise HttpError(
            resp=exc.resp,
            content=exc.content,
            uri=f"Drive file metadata for file_id={file_id}",
        ) from exc
