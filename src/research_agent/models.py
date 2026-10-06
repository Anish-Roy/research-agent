"""Chat models by role: cheap planner for plan/research/self-check, stronger writer, judge."""

from functools import cache
from typing import Literal

from langchain_openai import ChatOpenAI

from research_agent.config import settings

Role = Literal["planner", "writer", "judge"]


@cache
def get_model(role: Role, step: str) -> ChatOpenAI:
    """The model for `role`, named after the `step` that calls it.

    The name labels the call in traces (`generate-plan`, not `ChatOpenAI`). Keep step
    names stable: Langfuse evaluators and dashboards select observations by name.
    """
    model = getattr(settings, f"{role}_model")
    if not model:
        raise RuntimeError(f"{role.upper()}_MODEL is not set")
    return ChatOpenAI(model=model, api_key=settings.openai_api_key or None, name=step)
