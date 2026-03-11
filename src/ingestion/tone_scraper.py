"""
CRO Tone Scraper.

Extracts existing "Next Steps" column values from the master DataFrame and
uses Claude to synthesize a CRO Tone Profile — a structured description of the
CRO's writing voice, vocabulary, and sentence patterns.

The tone profile is injected into future Claude prompts as few-shot examples,
significantly improving voice matching quality.

Usage:
    python -m src.ingestion.tone_scraper
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

import pandas as pd

logger = logging.getLogger(__name__)

MIN_EXAMPLE_LENGTH = 20   # Characters — discard very short/empty values
MAX_EXAMPLES_FOR_PROFILE = 30  # Cap to avoid oversized prompts


def extract_next_steps(master_df: pd.DataFrame) -> list[str]:
    """
    Extract all non-empty "Next Steps" column values from the master DataFrame.

    Handles the canonical column name 'next_steps' (after normalization).
    Falls back to searching for columns containing "next" and "step".

    Args:
        master_df: The global joined + normalized DataFrame.

    Returns:
        Deduplicated list of Next Steps strings, filtered by minimum length.
    """
    col = _find_next_steps_column(master_df)
    if col is None:
        logger.warning(
            "No 'next_steps' column found. "
            "Check column_mappings.yaml → summary_tab → next_steps aliases."
        )
        return []

    raw_values = master_df[col].dropna().astype(str).str.strip()
    filtered = [v for v in raw_values if len(v) >= MIN_EXAMPLE_LENGTH and v.lower() not in ("nan", "none", "n/a", "")]

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for v in filtered:
        if v not in seen:
            seen.add(v)
            unique.append(v)

    logger.info("Extracted %d unique Next Steps examples from %d rows", len(unique), len(master_df))
    return unique


def build_cro_tone_profile(
    next_steps_examples: list[str],
    client,  # anthropic.Anthropic
    model: str = "claude-sonnet-4-6",
) -> dict:
    """
    Use Claude to analyze writing examples and produce a structured tone profile.

    Args:
        next_steps_examples: List of raw Next Steps strings from the CRO's sheets.
        client: An initialized Anthropic client (from src.llm.client).
        model: Claude model to use.

    Returns:
        Dict with keys: style_description, vocabulary_preferences, example_phrases,
        what_to_avoid, raw_examples (top examples used).
    """
    if not next_steps_examples:
        logger.warning("No examples provided — returning empty tone profile.")
        return _empty_profile()

    # Use a representative sample
    sample = next_steps_examples[:MAX_EXAMPLES_FOR_PROFILE]
    examples_block = "\n\n".join(f"{i+1}. {ex}" for i, ex in enumerate(sample))

    system_prompt = (
        "You are an expert at analyzing executive communication styles. "
        "Your task is to identify the writing patterns of a Chief Revenue Officer "
        "based on their actual account planning notes."
    )

    user_prompt = f"""Analyze these strategic account comments written by a CRO:

---
{examples_block}
---

Based on these examples, produce a structured JSON object describing this CRO's writing voice.
Return ONLY valid JSON with exactly these keys:

{{
  "style_description": "2-3 sentence description of their overall writing style",
  "vocabulary_preferences": ["list", "of", "preferred", "words", "or", "phrases"],
  "example_phrases": ["up to 5 representative short phrases or sentence starters from the examples"],
  "what_to_avoid": ["list of things that would NOT sound like this person"],
  "tone_keywords": ["3-5 single words that capture the tone: e.g. direct, urgent, strategic"]
}}

Return ONLY the JSON object, no other text."""

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=0.3,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        profile = json.loads(raw)
        profile["raw_examples"] = sample
        profile["generated"] = True
        profile["generated_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("CRO tone profile built from %d examples.", len(sample))
        return profile
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse tone profile JSON: %s", exc)
        return _empty_profile(raw_examples=sample)
    except Exception as exc:
        logger.error("Failed to build tone profile: %s", exc)
        return _empty_profile(raw_examples=sample)


def save_tone_profile(profile: dict, path: str = "config/cro_tone_profile.yaml") -> None:
    """Save tone profile to YAML (overwrites previous version)."""
    from src.utils.config_loader import save_yaml
    save_yaml(profile, path)
    logger.info("Tone profile saved to: %s", path)


def load_tone_profile(path: str = "config/cro_tone_profile.yaml") -> dict:
    """Load tone profile from YAML. Returns empty profile if file is missing."""
    from src.utils.config_loader import load_tone_profile as _load
    return _load()


def format_tone_for_prompt(profile: dict, max_examples: int = 5) -> str:
    """
    Format the tone profile into a string block for injection into the Claude system prompt.

    Args:
        profile: Loaded tone profile dict.
        max_examples: Max number of raw examples to include.

    Returns:
        A multi-line string ready for insertion into the system prompt.
        Returns empty string if profile is not generated.
    """
    if not profile.get("generated"):
        return ""

    lines = ["VOICE CALIBRATION — examples of how this CRO actually writes:"]

    raw = profile.get("raw_examples", [])[:max_examples]
    for i, ex in enumerate(raw, 1):
        lines.append(f'  {i}. "{ex}"')

    if profile.get("style_description"):
        lines.append(f"\nStyle notes: {profile['style_description']}")

    if profile.get("what_to_avoid"):
        avoid = ", ".join(profile["what_to_avoid"][:3])
        lines.append(f"Avoid: {avoid}")

    return "\n".join(lines)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _find_next_steps_column(df: pd.DataFrame) -> Optional[str]:
    """Find the Next Steps column — first by canonical name, then by substring."""
    if "next_steps" in df.columns:
        return "next_steps"
    for col in df.columns:
        col_lower = str(col).lower()
        if "next" in col_lower and "step" in col_lower:
            return col
    return None


def _empty_profile(raw_examples: Optional[List[str]] = None) -> dict:
    return {
        "generated": False,
        "generated_at": None,
        "style_description": "",
        "vocabulary_preferences": [],
        "example_phrases": [],
        "what_to_avoid": [],
        "tone_keywords": [],
        "raw_examples": raw_examples or [],
    }


if __name__ == "__main__":
    """
    Standalone runner to scrape tone and save profile.
    Run from project root: python -m src.ingestion.tone_scraper
    """
    import sys
    import os
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Quick test with the provided CSV
    csv_path = Path("data") / "raw" / "sample_tech_stake.csv"
    if not csv_path.exists():
        print("No sample CSV found. Please run the full ingest first.")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    examples = extract_next_steps(df)
    if not examples:
        print("No Next Steps examples found in the data.")
        sys.exit(0)

    print(f"Found {len(examples)} examples. First 3:")
    for ex in examples[:3]:
        print(f"  - {ex}")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("\nSet ANTHROPIC_API_KEY to build the full tone profile.")
        sys.exit(0)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    profile = build_cro_tone_profile(examples, client)
    save_tone_profile(profile)
    print(f"\nTone profile saved. Style: {profile.get('style_description', '')[:100]}")
