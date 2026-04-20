"""
Session persistence — save/load/resume.

Sessions are written as JSON files after every action.
Atomic write pattern (write .tmp then rename) prevents corruption on interrupt.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from src.session.state import SessionState, AccountDecision
from src.ingestion.joiner import get_account_key

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_SESSION_DIR = PROJECT_ROOT / "data" / "sessions"


def save_session(
    session: SessionState,
    session_dir: Path = DEFAULT_SESSION_DIR,
) -> Path:
    """
    Serialize SessionState to JSON using atomic write.

    Args:
        session: SessionState to save.
        session_dir: Directory to write session files.

    Returns:
        Path of the written session file.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    session.last_saved_at = datetime.now(timezone.utc).isoformat()

    target = session_dir / f"session_{session.session_id}.json"
    tmp = target.with_suffix(".json.tmp")

    tmp.write_text(json.dumps(session.to_dict(), indent=2, default=str), encoding="utf-8")
    tmp.rename(target)  # Atomic on POSIX

    logger.debug("Session saved: %s (%d decisions)", target.name, len(session.decisions))
    return target


def load_session(session_path: Path) -> SessionState:
    """
    Deserialize a JSON session file back to SessionState.

    Args:
        session_path: Path to session_{id}.json file.

    Returns:
        SessionState object.

    Raises:
        FileNotFoundError: If path doesn't exist.
        ValueError: If JSON is malformed.
    """
    if not session_path.exists():
        raise FileNotFoundError(f"Session file not found: {session_path}")
    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
        session = SessionState.from_dict(data)
        logger.info(
            "Session loaded: %s (%d/%d accounts reviewed)",
            session.session_id, len(session.decisions), session.total_accounts,
        )
        return session
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise ValueError(f"Session file is malformed: {session_path} — {exc}") from exc


def list_sessions(session_dir: Path = DEFAULT_SESSION_DIR) -> list[Path]:
    """
    List all session JSON files, newest first.

    Args:
        session_dir: Directory to search.

    Returns:
        List of Path objects sorted by modification time (newest first).
    """
    if not session_dir.exists():
        return []
    sessions = list(session_dir.glob("session_*.json"))
    return sorted(sessions, key=lambda p: p.stat().st_mtime, reverse=True)


def get_latest_session(session_dir: Path = DEFAULT_SESSION_DIR) -> Optional[Path]:
    """Return the most recent session file, or None if no sessions exist."""
    sessions = list_sessions(session_dir)
    return sessions[0] if sessions else None


def merge_session_with_df(
    session: SessionState,
    scored_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Re-attach session decisions back to the scored DataFrame.

    Adds columns:
    - final_comment (str or None)
    - review_status ("approved" | "skipped" | "pending")
    - regenerate_count (int)
    - edited (bool)

    Args:
        session: Loaded SessionState.
        scored_df: Scored master DataFrame.

    Returns:
        DataFrame with decision columns added.
    """
    df = scored_df.copy()
    df["final_comment"] = None
    df["review_status"] = "pending"
    df["regenerate_count"] = 0
    df["edited"] = False

    for _, row in df.iterrows():
        key = get_account_key(row)
        decision = session.decisions.get(key)
        if decision:
            idx = df[df.apply(get_account_key, axis=1) == key].index
            if not idx.empty:
                i = idx[0]
                df.at[i, "final_comment"] = decision.final_comment
                df.at[i, "review_status"] = decision.status
                df.at[i, "regenerate_count"] = decision.regenerate_count
                df.at[i, "edited"] = decision.edited

    return df


def record_decision(
    session: SessionState,
    account_key: str,
    status: str,
    final_comment: Optional[str] = None,
    original_comment: Optional[str] = None,
    edited: bool = False,
    regenerate_count: int = 0,
) -> SessionState:
    """
    Record an account decision and advance the session position.

    Args:
        session: Current SessionState.
        account_key: "REGION::AccountName" key.
        status: "approved" | "skipped".
        final_comment: Text of the approved/edited comment.
        original_comment: AI-generated original (before any edits).
        edited: True if the CRO modified the comment.
        regenerate_count: Number of times regenerate was clicked.

    Returns:
        Updated SessionState.
    """
    now = datetime.now(timezone.utc).isoformat()
    session.decisions[account_key] = AccountDecision(
        account_key=account_key,
        status=status,
        final_comment=final_comment,
        original_comment=original_comment,
        edited=edited,
        regenerate_count=regenerate_count,
        reviewed_at=now,
    )
    session.current_index += 1
    session.last_saved_at = now
    return session
