"""
YAML configuration loading utilities.

All modules load their configs through these helpers to ensure consistent
error messages and path resolution relative to the project root.
"""

import logging
from pathlib import Path
from typing import Any, Union

import yaml

logger = logging.getLogger(__name__)

# Project root is two levels up from src/utils/
PROJECT_ROOT = Path(__file__).parent.parent.parent


def load_yaml(path: Union[str, Path]) -> dict:
    """
    Load a YAML file and return its contents as a dict.

    Args:
        path: Absolute path or path relative to the project root.

    Returns:
        Parsed YAML contents as a dict.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the file contains invalid YAML.
    """
    resolved = Path(path) if Path(path).is_absolute() else PROJECT_ROOT / path
    if not resolved.exists():
        raise FileNotFoundError(f"Config file not found: {resolved}")
    with open(resolved, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    logger.debug("Loaded config: %s", resolved)
    return data or {}


def load_column_mappings() -> dict:
    """Load config/column_mappings.yaml."""
    return load_yaml("config/column_mappings.yaml")


def load_scoring_weights() -> dict:
    """Load config/scoring_weights.yaml."""
    return load_yaml("config/scoring_weights.yaml")


def load_prompt_templates() -> dict:
    """Load config/prompt_templates.yaml."""
    return load_yaml("config/prompt_templates.yaml")


def load_cro_persona() -> dict:
    """Load config/cro_persona.yaml."""
    return load_yaml("config/cro_persona.yaml")


def load_regions_config() -> dict:
    """Load config/regions.yaml."""
    return load_yaml("config/regions.yaml")


def load_tone_profile() -> dict:
    """
    Load config/cro_tone_profile.yaml.
    Returns empty dict with generated=False if file is absent or empty.
    """
    try:
        profile = load_yaml("config/cro_tone_profile.yaml")
        return profile or {"generated": False, "raw_examples": []}
    except FileNotFoundError:
        return {"generated": False, "raw_examples": []}


def save_yaml(data: dict, path: Union[str, Path]) -> None:
    """
    Write a dict to a YAML file.

    Args:
        data: Dict to serialize.
        path: Absolute path or path relative to the project root.
    """
    resolved = Path(path) if Path(path).is_absolute() else PROJECT_ROOT / path
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    logger.info("Saved config: %s", resolved)
