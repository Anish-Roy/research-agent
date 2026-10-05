"""write and check_citations."""

from typing import Literal

from langgraph.types import Command

from research_agent.citations import broken_ids, format_sources
from research_agent.models import get_model
from research_agent.state import ResearchState

WRITE_PROMPT = """Write a research report that answers the question below.
Use only the sources given.

Rules:
- Cite every factual claim with the ID of the source that supports it, like [S1].
  For several sources write [S1][S3]. Use only the IDs listed below.
- If the sources don't cover something, say so instead of guessing.
- Use markdown with short sections. Do not add a reference list; the IDs are enough.

Question: {question}

Sub-questions to cover:
{sub_questions}

Sources:
{sources}"""

REVISE_PROMPT = """

Your previous draft:
{draft}

Revise it to fix the following:
{issues}"""


def _issues(state: ResearchState) -> list[str]:
    """What the next draft must fix, gathered from every loop that leads back to `write`."""
    issues = []
    if broken := broken_ids(state.get("draft", ""), state.get("sources", [])):
        issues.append(f"These citation IDs don't exist; use only listed IDs: {', '.join(broken)}")
    for gap in state.get("gaps", []):
        cited = ", ".join(gap["source_ids"]) or "no citation"
        issues.append(f'Unsupported claim: "{gap["claim"]}" [{cited}]: {gap["reason"]}')
    if feedback := state.get("report_feedback"):
        issues.append(f"Reviewer feedback: {feedback}")
    return issues


async def write(state: ResearchState) -> dict:
    prompt = WRITE_PROMPT.format(
        question=state["question"],
        sub_questions="\n".join(f"- {q}" for q in state.get("sub_questions", [])),
        sources=format_sources(state.get("sources", [])),
    )
    if state.get("draft") and (issues := _issues(state)):
        prompt += REVISE_PROMPT.format(
            draft=state["draft"], issues="\n".join(f"- {i}" for i in issues)
        )

    reply = await get_model("writer").ainvoke(prompt)
    return {"draft": reply.text}


def check_citations(state: ResearchState) -> Command[Literal["write", "self_check"]]:
    """Send the draft back to `write` until every cited ID exists. Not capped."""
    if broken_ids(state.get("draft", ""), state.get("sources", [])):
        return Command(goto="write")
    return Command(goto="self_check")
