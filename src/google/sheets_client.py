"""
Google Sheets client for reading account planning data.

Provides:
- Reading any named tab as a pandas DataFrame
- Detecting available tab names in a spreadsheet
- Rate-limit retry for Google Sheets API (60 reads/min/user)
"""

import logging
import time
from typing import Optional, List, Dict

import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

# Sheets API quota: 60 reads/min/user. Proactively pace calls to stay under.
_MAX_RETRIES = 3
_RETRY_DELAY = 15  # seconds
_MIN_CALL_INTERVAL = 1.1  # seconds between calls (~54/min, safe margin)
_last_call_ts: float = 0.0


def _throttle() -> None:
    """Sleep as needed to keep Sheets API calls under 60/min."""
    global _last_call_ts
    elapsed = time.time() - _last_call_ts
    if elapsed < _MIN_CALL_INTERVAL:
        time.sleep(_MIN_CALL_INTERVAL - elapsed)
    _last_call_ts = time.time()


def _retry_on_rate_limit(func, *args, **kwargs):
    """Execute a Sheets API call, throttling first and retrying on 429."""
    for attempt in range(_MAX_RETRIES):
        _throttle()
        try:
            return func(*args, **kwargs)
        except HttpError as exc:
            if exc.resp.status == 429 and attempt < _MAX_RETRIES - 1:
                wait = _RETRY_DELAY * (attempt + 1)
                logger.warning("Rate limited — retrying in %ds (attempt %d/%d)", wait, attempt + 1, _MAX_RETRIES)
                time.sleep(wait)
            else:
                raise


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
        metadata = _retry_on_rate_limit(
            sheets_service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title")
            .execute
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
        result = _retry_on_rate_limit(
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=range_notation)
            .execute
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
    # Deduplicate column names (some sheets have repeated headers)
    seen = {}
    new_cols = []
    for col in df.columns:
        if col in seen:
            seen[col] += 1
            new_cols.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 0
            new_cols.append(col)
    df.columns = new_cols

    # Drop columns that are entirely empty (saves memory on wide sheets)
    empty_mask = df.fillna("").astype(str).apply(lambda c: c.str.strip().eq("").all())
    empty_cols = empty_mask[empty_mask].index.tolist()
    if empty_cols:
        df = df.drop(columns=empty_cols)
    logger.info(
        "Read '%s' from %s: %d rows × %d columns (dropped %d empty cols)",
        sheet_name, spreadsheet_id, len(df), len(df.columns), len(empty_cols),
    )
    return df


def find_account_cell(
    sheets_service,
    spreadsheet_id: str,
    sheet_name: str,
    account_name: str,
    target_col: str = "account_name",
    fallback_col: str = "account_name",
) -> dict:
    """
    Locate an account's row in a sheet and return cell reference + cell text
    for the target column. Falls back to account name column if target is empty.

    Args:
        sheets_service: Authenticated Sheets API service.
        spreadsheet_id: Google Sheets file ID.
        sheet_name: Tab name to search in.
        account_name: Account name to match (case-insensitive).
        target_col: Preferred column to anchor on (canonical name).
        fallback_col: Fallback column if target cell is empty.

    Returns:
        Dict with keys: found (bool), cell_ref (str like "U5"),
        cell_text (str), sheet_row (int), debug (str).
    """
    result = {"found": False, "cell_ref": "", "cell_text": "", "sheet_row": 0, "debug": ""}

    # Read raw sheet values
    try:
        resp = _retry_on_rate_limit(
            sheets_service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"'{sheet_name}'")
            .execute
        )
    except HttpError as exc:
        result["debug"] = f"Failed to read sheet: {exc}"
        return result

    rows = resp.get("values", [])
    if not rows:
        result["debug"] = "Sheet is empty"
        return result

    # Detect header row (skip empty rows, long first cells, stats rows)
    header_idx = 0
    while header_idx < len(rows):
        row = rows[header_idx]
        if not any(str(c).strip() for c in row):
            header_idx += 1
            continue
        first_cell = str(row[0]).strip() if row else ""
        if len(first_cell) > 60:
            header_idx += 1
            continue
        other_cells = [str(c).strip() for c in row[1:] if str(c).strip()]
        if other_cells and sum(1 for c in other_cells if c.endswith("%")) / len(other_cells) > 0.4:
            header_idx += 1
            continue
        break

    if header_idx >= len(rows):
        result["debug"] = "No detectable header row"
        return result

    headers = [str(h).strip().lower() for h in rows[header_idx]]

    # Find account column
    _ACCOUNT_CANDIDATES = ["account_name", "customer name", "account name",
                           "customer_name", "company", "company name", "name"]
    acct_col_idx = None
    for candidate in _ACCOUNT_CANDIDATES:
        for i, h in enumerate(headers):
            if h == candidate.lower():
                acct_col_idx = i
                break
        if acct_col_idx is not None:
            break

    if acct_col_idx is None:
        result["debug"] = f"Account column not found. Headers: {headers[:10]}"
        return result

    # Find target column index
    target_col_idx = None
    if target_col == "account_name":
        target_col_idx = acct_col_idx
    else:
        _NEXT_STEPS_CANDIDATES = ["next_steps", "next steps", "next steps & execution strategy",
                                  "next steps and execution strategy"]
        for candidate in _NEXT_STEPS_CANDIDATES if target_col == "next_steps" else [target_col]:
            for i, h in enumerate(headers):
                if candidate.lower() in h:
                    target_col_idx = i
                    break
            if target_col_idx is not None:
                break

    # Match account row
    account_lower = account_name.strip().lower()
    data_rows = rows[header_idx + 1:]

    for row_offset, data_row in enumerate(data_rows):
        if acct_col_idx >= len(data_row):
            continue
        cell_name = str(data_row[acct_col_idx]).strip().lower()
        if cell_name != account_lower:
            continue

        sheet_row = header_idx + 2 + row_offset  # 1-indexed

        # Try target column first, fall back to account name column
        chosen_col_idx = None
        cell_text = ""

        if target_col_idx is not None and target_col_idx < len(data_row):
            val = str(data_row[target_col_idx]).strip()
            if val and val.lower() not in ("nan", "none", "n/a", ""):
                chosen_col_idx = target_col_idx
                cell_text = val

        if chosen_col_idx is None:
            # Fallback to account name cell
            chosen_col_idx = acct_col_idx
            cell_text = str(data_row[acct_col_idx]).strip()

        col_letter = _col_index_to_letter(chosen_col_idx + 1)
        result["found"] = True
        result["cell_ref"] = f"{col_letter}{sheet_row}"
        result["cell_text"] = cell_text
        result["sheet_row"] = sheet_row
        result["debug"] = f"Matched row {sheet_row}, col {col_letter} (idx {chosen_col_idx})"
        return result

    result["debug"] = f"Account '{account_name}' not found in sheet"
    return result


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_column(df: pd.DataFrame, canonical_name: str) -> Optional[str]:
    """Case-insensitive column lookup. Returns the actual column name or None."""
    target = canonical_name.lower().strip()
    for col in df.columns:
        if str(col).lower().strip() == target:
            return col
    return None


def _col_index_to_letter(col_index: int) -> str:
    """Convert 1-indexed column number to letter(s). E.g., 1→A, 27→AA."""
    result = ""
    while col_index > 0:
        col_index, remainder = divmod(col_index - 1, 26)
        result = chr(65 + remainder) + result
    return result


