"""
Anthropic Claude API client wrapper.

Provides a robust call_claude() function with:
- API key loading from environment/Streamlit secrets
- 3-attempt exponential backoff on transient errors
- Consistent error logging
"""

import logging
import os
import time
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 512
DEFAULT_TEMPERATURE = 0.7
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds


def get_anthropic_client(api_key: Optional[str] = None) -> anthropic.Anthropic:
    """
    Return an initialized Anthropic client.

    Resolution order for API key:
    1. Explicit api_key argument
    2. Streamlit secrets: st.secrets["ANTHROPIC_API_KEY"]
    3. Environment variable: ANTHROPIC_API_KEY

    Raises:
        EnvironmentError: If no API key is found.
    """
    if api_key:
        return anthropic.Anthropic(api_key=api_key)

    # Try Streamlit secrets
    try:
        import streamlit as st
        key = st.secrets.get("ANTHROPIC_API_KEY")
        if key:
            return anthropic.Anthropic(api_key=key)
    except Exception:
        pass

    # Try environment variable
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return anthropic.Anthropic(api_key=env_key)

    raise EnvironmentError(
        "No Anthropic API key found. Set ANTHROPIC_API_KEY in:\n"
        "  1. .streamlit/secrets.toml\n"
        "  2. Environment variable ANTHROPIC_API_KEY"
    )


def call_claude(
    client: anthropic.Anthropic,
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
) -> str:
    """
    Make a single Claude API call and return the response text.

    Retries up to MAX_RETRIES times with exponential backoff on transient errors.

    Args:
        client: Initialized Anthropic client.
        system_prompt: The system-level prompt (CRO persona + voice rules).
        user_prompt: The user-level prompt (account data).
        model: Claude model identifier.
        max_tokens: Maximum response length.
        temperature: Generation temperature (0.7 = first gen, 0.85 = regen).

    Returns:
        The text content of Claude's response.

    Raises:
        anthropic.APIError: After all retries are exhausted.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = response.content[0].text.strip()
            logger.debug(
                "Claude response (model=%s, attempt=%d): %s...",
                model, attempt, text[:80],
            )
            return text
        except anthropic.RateLimitError as exc:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning("Rate limit hit (attempt %d/%d). Retrying in %.1fs...", attempt, MAX_RETRIES, delay)
            time.sleep(delay)
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                delay = RETRY_BASE_DELAY * attempt
                logger.warning(
                    "API server error %d (attempt %d/%d). Retrying in %.1fs...",
                    exc.status_code, attempt, MAX_RETRIES, delay,
                )
                time.sleep(delay)
            else:
                logger.error("Claude API error %d: %s", exc.status_code, exc.message)
                raise
        except anthropic.APIConnectionError:
            delay = RETRY_BASE_DELAY * attempt
            logger.warning("Connection error (attempt %d/%d). Retrying in %.1fs...", attempt, MAX_RETRIES, delay)
            time.sleep(delay)

    raise anthropic.APIConnectionError(
        request=None,
        message=f"Claude API call failed after {MAX_RETRIES} attempts."
    )
