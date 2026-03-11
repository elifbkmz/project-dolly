"""
Google Sheets client for reading account planning data and writing back CRO comments.

Provides:
- Reading any named tab as a pandas DataFrame
- Detecting available tab names in a spreadsheet
- Batch-writing CRO-approved comments back to a Summary tab
"""

import logging
from typing import Optional, List, Dict

import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account

logger = logging.getLogger(__name__)


def build_sheets_service(credentials: service_account.Credentials):
    """Build and return a Google Sheets API service object."""
    return build("sheets", "v4", credentials=credentials)


def detect_sheet_names(sheets_service, spreadsheet_id: str) -> List[str]:
    """
    Returns all tab names in a spreadsheet.

    Args:
        sheets_service: Authenticated Sheets API service.
        spreadsheet_id: Google Sheets spreadsheet ID.

    Returns:
        List of sheet/tab names in order.
    """
    try:
        metadata = (
            sheets_service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title")
            .execute()
        )
        names = [s["properties"]["title"] for s in metadata.get("sheets", [])]
        logger.debug("Spreadsheet %s tabs: %s", spreadsheet_id, names)
        return names
    except HttpError as exc:
        raise HttpError(
            resp=exc.resp,
            content=exc.content,
            uri=f"Sheets metadata for spreadsheet_id={spreadsheet_id}",
        ) from exc


def read_sheet_as_dataframe(
    sheets_service,
    spreadsheet_id: str,
    sheet_name: str,
    header_row: int = 0,
) -> pd.DataFrame:
    """
    Reads a named tab from a Google Sheet and returns it as a DataFrame.

    The first non-empty row is treated as column headers.
    All values are returned as strings (caller is responsible for type conversion).

    Args:
        sheets_service: Authenticated Sheets API service.
        spreadsheet_id: Google Sheets spreadsheet ID.
        sheet_name: Exact tab name to read.
        header_row: Index of the header row in the raw values (default 0).

    Returns:
        pandas DataFrame. Empty DataFrame if the sheet has no data.

    Raises:
        ValueError: If sheet_name is not found in the spreadsheet.
    """
    range_notation = f"'{sheet_name}'"
    try:
        result = (
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_notation)
            .execute()
        )
    except HttpError as exc:
        if exc.resp.status == 400:
            raise ValueError(
                f"Sheet tab '{sheet_name}' not found in spreadsheet {spreadsheet_id}. "
                f"Check detect_sheet_names() for available tabs."
            ) from exc
        raise

    rows = result.get("values", [])
    if not rows:
        logger.warning("Sheet '%s' in %s is empty.", sheet_name, spreadsheet_id)
        return pd.DataFrame()

    # Find the header row:
    # Skip completely empty rows, instruction rows (first cell >60 chars),
    # and stats rows (most non-empty cells after the first are percentages).
    effective_header_idx = header_row
    while effective_header_idx < len(rows):
        row = rows[effective_header_idx]
        if not any(row):
            # Completely empty row — skip
            effective_header_idx += 1
            continue
        first_cell = str(row[0]).strip() if row else ""
        if len(first_cell) > 60:
            # First cell is too long to be a column header — skip instruction/note row
            logger.debug("Skipping instruction row %d in '%s': first cell len=%d", effective_header_idx, sheet_name, len(first_cell))
            effective_header_idx += 1
            continue
        # Skip "stats" rows where most non-empty cells (after the first) are percentages
        if len(row) > 1:
            other_cells = [str(c).strip() for c in row[1:] if str(c).strip()]
            if other_cells and sum(1 for c in other_cells if c.endswith("%")) / len(other_cells) > 0.4:
                logger.debug("Skipping stats row %d in '%s': most cells are percentages", effective_header_idx, sheet_name)
                effective_header_idx += 1
                continue
        break

    if effective_header_idx >= len(rows):
        logger.warning("Sheet '%s' has no header row.", sheet_name)
        return pd.DataFrame()

    headers = list(rows[effective_header_idx])
    data_rows = rows[effective_header_idx + 1:]

    # Determine true column width: max across headers AND all data rows
    max_cols = max(
        len(headers),
        max((len(r) for r in data_rows), default=0)
    )

    # Pad headers with generated names for any extra data columns
    if len(headers) < max_cols:
        headers += [f"_col_{i}" for i in range(len(headers), max_cols)]

    # Replace junk header cells (empty, pure numbers, currency values like "$233,276")
    import re as _re
    _junk_pattern = _re.compile(r"^[\$\€\£]?[\d,\.]+%?$")
    for i, h in enumerate(headers):
        cell = str(h).strip()
        if not cell or _junk_pattern.match(cell):
            headers[i] = f"_col_{i}"

    # Pad every data row to max_cols
    padded_rows = [row + [""] * (max_cols - len(row)) for row in data_rows]

    df = pd.DataFrame(padded_rows, columns=headers)
    # Drop fully empty rows
    df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)].reset_index(drop=True)
    logger.info(
        "Read '%s' from %s: %d rows × %d columns",
        sheet_name, spreadsheet_id, len(df), len(df.columns),
    )
    return df


def write_comments_to_summary(
    sheets_service,
    spreadsheet_id: str,
    sheet_name: str,
    account_comment_map: Dict[str, str],
    account_col: str = "account_name",
    comment_col: str = "CRO Comment",
) -> tuple:
    """
    Writes approved CRO comments back into the Summary tab.

    Reads raw sheet values directly (no column normalization) so that row
    numbers are exact. Tries multiple common account-column name variants.
    Finds or creates the 'CRO Comment' column. Uses batchUpdate for efficiency.

    Args:
        sheets_service: Authenticated Sheets API service.
        spreadsheet_id: Target spreadsheet ID.
        sheet_name: Summary tab name.
        account_comment_map: {canonical_account_name: approved_comment_text}
        account_col: Preferred canonical name for the account column.
        comment_col: Column name to write comments into (created if absent).

    Returns:
        Tuple of (count_written: int, debug_info: dict) where debug_info contains
        diagnostic details about the write operation.
    """
    debug_info: Dict = {
        "sheet_name": sheet_name,
        "header_idx": None,
        "headers_found": [],
        "acct_col_name": None,
        "acct_col_idx": None,
        "comment_col_idx": None,
        "comment_col_letter": None,
        "cells_written": [],
        "sheet_sample_accounts": [],
        "accounts_looked_for": list(account_comment_map.keys()),
        "error": None,
    }

    if not account_comment_map:
        logger.info("No approved comments to write back.")
        return 0, debug_info

    # ── Read raw sheet values (bypass DataFrame so row numbers stay exact) ────
    range_notation = f"'{sheet_name}'"
    try:
        result = (
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_notation)
            .execute()
        )
    except HttpError as exc:
        logger.error("Failed to read sheet '%s' for write-back: %s", sheet_name, exc)
        raise

    rows = result.get("values", [])
    if not rows:
        logger.warning("Summary sheet '%s' is empty — cannot write back.", sheet_name)
        debug_info["error"] = "Sheet is empty"
        return 0, debug_info

    # ── Detect header row (mirrors read_sheet_as_dataframe logic) ─────────────
    header_idx = 0
    skipped_reasons: List[str] = []
    while header_idx < len(rows):
        row = rows[header_idx]
        if not any(str(c).strip() for c in row):
            skipped_reasons.append(f"row {header_idx+1}: empty")
            header_idx += 1
            continue
        first_cell = str(row[0]).strip() if row else ""
        if len(first_cell) > 60:
            skipped_reasons.append(f"row {header_idx+1}: first cell too long ({len(first_cell)} chars): '{first_cell[:40]}...'")
            header_idx += 1
            continue
        other_cells = [str(c).strip() for c in row[1:] if str(c).strip()]
        if other_cells and sum(1 for c in other_cells if c.endswith("%")) / len(other_cells) > 0.4:
            skipped_reasons.append(f"row {header_idx+1}: stats row (mostly %)")
            header_idx += 1
            continue
        break

    debug_info["header_idx"] = header_idx
    debug_info["skipped_rows"] = skipped_reasons

    if header_idx >= len(rows):
        logger.warning("Sheet '%s' has no detectable header row.", sheet_name)
        debug_info["error"] = "No detectable header row"
        return 0, debug_info

    headers = [str(h).strip() for h in rows[header_idx]]
    data_rows = rows[header_idx + 1:]
    debug_info["headers_found"] = headers[:15]  # first 15 headers for debug

    # ── Find account column — try canonical name + common raw sheet variants ──
    _ACCOUNT_CANDIDATES = [
        account_col,       # "account_name"
        "customer name",   # most common raw sheet header
        "account name",
        "customer_name",
        "company",
        "company name",
        "name",
    ]
    acct_col_idx: Optional[int] = None
    for candidate in _ACCOUNT_CANDIDATES:
        for i, h in enumerate(headers):
            if h.lower() == candidate.lower():
                acct_col_idx = i
                break
        if acct_col_idx is not None:
            debug_info["acct_col_name"] = candidate
            break

    if acct_col_idx is None:
        logger.error(
            "Account column not found in sheet '%s'. Headers: %s",
            sheet_name, headers[:10],
        )
        debug_info["error"] = f"Account column not found. Headers seen: {headers[:10]}"
        return 0, debug_info

    debug_info["acct_col_idx"] = acct_col_idx

    # ── Find or create CRO Comment column ────────────────────────────────────
    comment_col_idx: Optional[int] = None
    for i, h in enumerate(headers):
        if h.lower() == comment_col.lower():
            comment_col_idx = i
            break

    if comment_col_idx is None:
        # Append at the end of the header row
        comment_col_idx = len(headers)
        header_sheet_row = header_idx + 1  # 1-indexed
        _write_cell(
            sheets_service, spreadsheet_id, sheet_name,
            row=header_sheet_row, col=comment_col_idx + 1, value=comment_col,
        )
        logger.info("Created column '%s' in sheet '%s'", comment_col, sheet_name)
        debug_info["comment_col_created"] = True
    else:
        debug_info["comment_col_created"] = False

    debug_info["comment_col_idx"] = comment_col_idx
    col_letter = _col_index_to_letter(comment_col_idx + 1)
    debug_info["comment_col_letter"] = col_letter

    # ── Match accounts and build batch updates ────────────────────────────────
    # Sheet row for data_rows[i] = header_idx + 2 + i  (1-indexed, skipped rows accounted for)
    lookup = {name.strip().lower(): comment for name, comment in account_comment_map.items()}
    updates: List[dict] = []
    written = 0

    # Collect sample of what account names are actually in the sheet
    sheet_sample = []
    for data_row in data_rows[:10]:
        if acct_col_idx < len(data_row):
            v = str(data_row[acct_col_idx]).strip()
            if v:
                sheet_sample.append(v)
    debug_info["sheet_sample_accounts"] = sheet_sample

    for row_offset, data_row in enumerate(data_rows):
        if acct_col_idx >= len(data_row):
            continue
        cell_name = str(data_row[acct_col_idx]).strip().lower()
        if not cell_name or cell_name in ("nan", "none", ""):
            continue
        comment = lookup.get(cell_name)
        if comment is None:
            continue
        sheet_row = header_idx + 2 + row_offset  # 1-indexed, accounts for skipped rows
        cell_range = f"'{sheet_name}'!{col_letter}{sheet_row}"
        updates.append({"range": cell_range, "values": [[comment]]})

        # Capture a few context columns so user can see which row variant this is
        row_context = {}
        for ctx_i, ctx_h in enumerate(headers[:12]):
            if ctx_i == acct_col_idx:
                continue
            if ctx_i < len(data_row) and str(data_row[ctx_i]).strip():
                row_context[ctx_h] = str(data_row[ctx_i]).strip()

        debug_info["cells_written"].append({
            "account": str(data_row[acct_col_idx]).strip(),  # original casing
            "cell": f"{col_letter}{sheet_row}",
            "row_offset": row_offset,
            "row_context": row_context,
        })
        written += 1
        logger.debug("Queued: '%s' → %s%d", cell_name, col_letter, sheet_row)

    if not updates:
        sample = [
            str(r[acct_col_idx]).strip() for r in data_rows[:5] if acct_col_idx < len(r)
        ]
        logger.warning(
            "No matching accounts found in '%s'. Looked for: %s. Sheet sample: %s",
            sheet_name, list(account_comment_map.keys()), sample,
        )
        debug_info["error"] = f"No matching accounts. Looked for: {list(account_comment_map.keys())}. Sheet sample: {sample}"
        return 0, debug_info

    # ── Batch write to Sheets ─────────────────────────────────────────────────
    body = {"valueInputOption": "RAW", "data": updates}
    try:
        sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id, body=body
        ).execute()
        logger.info("Wrote %d comments to '%s' in %s", written, sheet_name, spreadsheet_id)
    except HttpError as exc:
        logger.error("Failed to write comments: %s", exc)
        raise

    return written, debug_info


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_column(df: pd.DataFrame, canonical_name: str) -> Optional[str]:
    """Case-insensitive column lookup. Returns the actual column name or None."""
    target = canonical_name.lower().strip()
    for col in df.columns:
        if str(col).lower().strip() == target:
            return col
    return None


def _write_cell(sheets_service, spreadsheet_id: str, sheet_name: str, row: int, col: int, value: str) -> None:
    """Write a single cell value (1-indexed row and col)."""
    col_letter = _col_index_to_letter(col)
    cell_range = f"'{sheet_name}'!{col_letter}{row}"
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=cell_range,
        valueInputOption="RAW",
        body={"values": [[value]]},
    ).execute()


def _col_index_to_letter(col_index: int) -> str:
    """Convert 1-indexed column number to letter(s). E.g., 1→A, 27→AA."""
    result = ""
    while col_index > 0:
        col_index, remainder = divmod(col_index - 1, 26)
        result = chr(65 + remainder) + result
    return result
