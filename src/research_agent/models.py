"""Chat models by role: cheap planner for plan/research/self-check, stronger writer, judge."""

from functools import cache
from typing import Literal

from langchain_openai import ChatOpenAI

from research_agent.config import settings

Role = Literal["planner", "writer", "judge"]


@cache
def get_model(role: Role) -> ChatOpenAI:
    name = getattr(settings, f"{role}_model")
    if not name:
        raise RuntimeError(f"{role.upper()}_MODEL is not set")
    return ChatOpenAI(model=name, api_key=settings.openai_api_key or None)
