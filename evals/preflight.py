"""Checks to run before an eval, so a bad key fails in seconds, not after a whole run."""

import sys

import openai

from research_agent.config import settings


def require_openai_key() -> None:
    """Exit unless the OpenAI key works. Listing models is free."""
    try:
        openai.OpenAI(api_key=settings.openai_api_key or None).models.list()
    except openai.AuthenticationError as e:
        sys.exit(f"OpenAI key rejected ({e.code or e.status_code}); update OPENAI_API_KEY in .env")
