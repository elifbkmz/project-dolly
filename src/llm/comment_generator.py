"""
CRO comment generation — single account and batch.

Wraps prompt building + Claude API call into a single interface.
"""

import logging
from typing import Optional, List

import pandas as pd

from src.llm.client import call_claude, DEFAULT_MODEL
from src.llm.prompt_builder import build_system_prompt, build_account_user_prompt
from src.utils.config_loader import load_prompt_templates, load_cro_persona, load_tone_profile

logger = logging.getLogger(__name__)


def generate_comment_for_account(
    row: pd.Series,
    scoring: dict,
    client,
    system_prompt: str,
    user_prompt_template: str,
    templates: dict,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
) -> str:
    """
    Generate a CRO-voice comment for a single account.

    Args:
        row: Account row from the scored master DataFrame.
        scoring: Scoring results dict for this row.
        client: Initialized Anthropic client.
        system_prompt: Pre-built system prompt (call build_system_prompt() once).
        user_prompt_template: Template string (from prompt_templates.yaml).
        templates: Full templates dict (for sentence_count etc.).
        model: Claude model.
        temperature: 0.7 first gen, 0.85 regen.

    Returns:
        Generated comment text string.
    """
    user_prompt = build_account_user_prompt(row, scoring, templates)
    comment = call_claude(
        client=client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=temperature,
    )
    return comment


def batch_generate_comments(
    scored_df: pd.DataFrame,
    client,
    system_prompt: str,
    templates: dict,
    model: str = DEFAULT_MODEL,
    tiers: Optional[List[str]] = None,
    top_n: Optional[int] = None,
    progress_callback=None,
) -> dict[str, str]:
    """
    Generate comments for all (or filtered) accounts in the scored DataFrame.

    Args:
        scored_df: Scored master DataFrame.
        client: Initialized Anthropic client.
        system_prompt: Pre-built system prompt.
        templates: Loaded prompt_templates.yaml.
        model: Claude model.
        tiers: List of tiers to generate for, e.g. ["P1", "P2"]. None = all.
        top_n: If set, only generate for the top N accounts.
        progress_callback: Optional callable(current, total) for Streamlit progress bar.

    Returns:
        Dict mapping account_key → comment_text.
        Accounts that fail generation are omitted (logged as warnings).
    """
    from src.ingestion.joiner import get_account_key

    # Filter to requested tiers
    df = scored_df.copy()
    if tiers:
        df = df[df["attention_tier"].isin(tiers)]
    if top_n:
        df = df.head(top_n)

    total = len(df)
    logger.info("Batch generating comments for %d accounts (model=%s)...", total, model)

    results: dict[str, str] = {}
    for i, (_, row) in enumerate(df.iterrows()):
        account_key = get_account_key(row)
        # Build scoring dict from row columns
        scoring = _extract_scoring_from_row(row)
        try:
            comment = generate_comment_for_account(
                row=row,
                scoring=scoring,
                client=client,
                system_prompt=system_prompt,
                user_prompt_template=templates.get("user_prompt_template", ""),
                templates=templates,
                model=model,
                temperature=0.7,
            )
            results[account_key] = comment
            logger.debug("[%d/%d] Generated comment for: %s", i + 1, total, account_key)
        except Exception as exc:
            logger.warning("Failed to generate comment for '%s': %s", account_key, exc)

        if progress_callback:
            progress_callback(i + 1, total)

    logger.info("Batch complete: %d/%d comments generated.", len(results), total)
    return results


def build_shared_system_prompt(
    templates: Optional[dict] = None,
    cro_config: Optional[dict] = None,
    tone_profile: Optional[dict] = None,
) -> str:
    """
    Convenience function to build the system prompt from config files.
    Loads configs automatically if not provided.
    """
    if templates is None:
        templates = load_prompt_templates()
    if cro_config is None:
        cro_config = load_cro_persona()
    if tone_profile is None:
        tone_profile = load_tone_profile()
    return build_system_prompt(templates, cro_config, tone_profile)


def _extract_scoring_from_row(row: pd.Series) -> dict:
    """Extract scoring result columns from a scored DataFrame row into a dict."""
    scoring_cols = [
        "nrr_score", "nrr_tier", "nrr_raw", "nrr_display", "nrr_missing",
        "threading_score", "threading_tier", "contact_count", "threading_missing",
        "expansion_score", "expansion_tier", "insider_product_count",
        "insider_channels", "total_channels", "competitor_channels", "whitespace_channels",
        "expansion_channel_count", "composite_score", "attention_tier",
        "primary_signal", "hard_override",
    ]
    scoring = {}
    for col in scoring_cols:
        if col in row.index:
            val = row[col]
            # Guard: duplicate columns may return a Series — take the first scalar
            if isinstance(val, pd.Series):
                val = val.iloc[0] if not val.empty else None
            # Deserialize lists stored as strings in CSV
            if isinstance(val, str) and val.startswith("["):
                try:
                    import ast
                    val = ast.literal_eval(val)
                except Exception:
                    pass
            scoring[col] = val
    return scoring
