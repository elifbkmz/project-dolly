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


def list_sheets_in_folder(drive_service, folder_id: str) -> List[dict]:
    """
    Lists all Google Sheets files in a Drive folder.

    Args:
        drive_service: Authenticated Drive API service.
        folder_id: Google Drive folder ID (from the folder URL).

    Returns:
        List of dicts with keys: id, name, modifiedTime.

    Raises:
        HttpError: If the folder is not accessible (wrong ID or no permission).
    """
    query = (
        f"'{folder_id}' in parents "
        "and mimeType='application/vnd.google-apps.spreadsheet' "
        "and trashed=false"
    )
    try:
        response = (
            drive_service.files()
            .list(
                q=query,
                fields="files(id, name, modifiedTime)",
                orderBy="name",
                pageSize=100,
            )
            .execute()
        )
        files = response.get("files", [])
        logger.info("Found %d spreadsheet(s) in folder %s", len(files), folder_id)
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
    Discovers regional spreadsheet IDs by matching filenames against patterns.

    If pattern_map is empty OR no patterns match any file, falls back to
    auto-discovery: every spreadsheet in the folder becomes its own region,
    keyed by filename.

    Args:
        drive_service: Authenticated Drive API service.
        folder_id: Google Drive folder ID.
        pattern_map: Dict mapping region name to fnmatch pattern.
                     Example: {"APAC": "*APAC*", "EMEA": "*EMEA*"}
                     Pass an empty dict to auto-discover all files.

    Returns:
        Dict mapping region name to spreadsheet ID.
    """
    files = list_sheets_in_folder(drive_service, folder_id)

    if not files:
        raise ValueError(
            f"No Google Sheets files found in Drive folder '{folder_id}'. "
            "Check that the service account has Viewer access to the folder."
        )

    # Pattern-based matching
    result: Dict[str, str] = {}
    if pattern_map:
        for region, pattern in pattern_map.items():
            matches = [f for f in files if fnmatch.fnmatch(f["name"], pattern)]
            if not matches:
                logger.warning(
                    "No file found for region '%s' with pattern '%s' in folder %s",
                    region, pattern, folder_id,
                )
                continue
            if len(matches) > 1:
                logger.warning(
                    "Multiple files match region '%s' pattern '%s': %s — using first.",
                    region, pattern, [m["name"] for m in matches],
                )
            chosen = matches[0]
            result[region] = chosen["id"]
            logger.info("Region '%s' → '%s' (id: %s)", region, chosen["name"], chosen["id"])

    # Fallback: auto-discover all files as regions (filename = region key)
    if not result:
        logger.warning(
            "No pattern matches found — auto-discovering all %d file(s) as regions.", len(files)
        )
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
    return name.strip() or filename


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
