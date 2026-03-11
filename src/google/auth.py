"""
Google Service Account authentication.

Loads credentials from Streamlit secrets (production) or a local JSON file (development).
No browser interaction required — fully headless.

Setup (one-time):
1. Create a GCP project → enable Drive API + Sheets API
2. Create a Service Account → download JSON key
3. Share your Google Drive folder with the service account email
4. Add the JSON key to .streamlit/secrets.toml:
   GOOGLE_SERVICE_ACCOUNT_JSON = '''{ ... full JSON key ... }'''
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, List

from google.oauth2 import service_account

logger = logging.getLogger(__name__)

REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

# Local fallback path for development (gitignored)
LOCAL_CREDENTIALS_PATH = Path(__file__).parent.parent.parent / "credentials" / "service_account.json"


def get_google_credentials(
    scopes: List[str] = REQUIRED_SCOPES,
    local_path: Optional[Path] = None,
) -> service_account.Credentials:
    """
    Returns Google Service Account credentials.

    Resolution order:
    1. Streamlit secrets: st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"] (JSON string)
    2. Environment variable: GOOGLE_SERVICE_ACCOUNT_JSON (JSON string)
    3. Local file: credentials/service_account.json

    Args:
        scopes: OAuth scopes to request.
        local_path: Override path for local JSON key file.

    Returns:
        Scoped service_account.Credentials ready for use with Google API clients.

    Raises:
        EnvironmentError: If no credentials source is found.
        ValueError: If the credentials JSON is malformed.
    """
    info = _load_service_account_info(local_path)
    try:
        credentials = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        logger.info("Google credentials loaded for: %s", info.get("client_email", "unknown"))
        return credentials
    except Exception as exc:
        raise ValueError(f"Failed to create credentials from service account info: {exc}") from exc


def _load_service_account_info(local_path: Optional[Path] = None) -> dict:
    """Try all credential sources in priority order."""

    # 1. Streamlit secrets (production) — highest priority
    try:
        import streamlit as st
        # Try as a plain string key (triple-quoted JSON in secrets.toml)
        raw = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if raw is not None:
            logger.debug("Loading credentials from Streamlit secrets (string key)")
            if isinstance(raw, str):
                try:
                    return json.loads(raw.strip())
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"GOOGLE_SERVICE_ACCOUNT_JSON in .streamlit/secrets.toml is not valid JSON: {exc}\n"
                        "Tip: save the JSON file to credentials/service_account.json instead."
                    ) from exc
            else:
                # Streamlit parsed the TOML block as a dict — use directly
                return dict(raw)

        # Try as a TOML table [GOOGLE_SERVICE_ACCOUNT_JSON] — alternative format
        try:
            section = st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]
            return dict(section)
        except (KeyError, AttributeError):
            pass

    except ImportError:
        pass  # Streamlit not installed
    except Exception:
        pass  # Any other Streamlit/TOML error — fall through to file

    # 2. Local file (development) — checked before env var so an explicit file always wins
    path = local_path or LOCAL_CREDENTIALS_PATH
    if path.exists():
        logger.debug("Loading credentials from local file: %s", path)
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Service account JSON file is malformed: {path}") from exc

    # 3. Environment variable (CI / alternative deployment)
    raw_env = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw_env:
        logger.debug("Loading credentials from environment variable")
        try:
            return json.loads(raw_env)
        except json.JSONDecodeError as exc:
            raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not valid JSON") from exc

    raise EnvironmentError(
        "No Google credentials found. Provide one of:\n"
        "  1. Streamlit secret: GOOGLE_SERVICE_ACCOUNT_JSON\n"
        "  2. Environment variable: GOOGLE_SERVICE_ACCOUNT_JSON\n"
        f"  3. Local file: {LOCAL_CREDENTIALS_PATH}"
    )
