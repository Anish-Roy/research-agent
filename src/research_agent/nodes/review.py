"""self_check, approve_report, and save_report."""

import logging
import re
from datetime import UTC, datetime
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from research_agent.citations import format_sources
from research_agent.config import settings
from research_agent.models import get_model
from research_agent.nodes.research import gap_tasks
from research_agent.state import Gap, ResearchState, Source

logger = logging.getLogger(__name__)

MAX_RESEARCH_LOOPS = 2

SELF_CHECK_PROMPT = """Check the draft report below against its sources.

For each factual claim, check that the sources it cites (like [S1]) actually support it.
List only the claims that fail: the source doesn't say it, says something different,
or the claim has no citation. For each one, give the sub-question it answers (copied
exactly from the list below), the claim quoted briefly, the source IDs it cites, and the
reason it failed. If every claim is supported, return an empty list.

Sub-questions:
{sub_questions}

Draft:
{draft}

Sources:
{sources}"""


class _Gap(BaseModel):
    sub_question: str = Field(description="The sub-question the claim answers, copied exactly")
    claim: str = Field(description="The unsupported claim, quoted briefly")
    source_ids: list[str] = Field(description="Source IDs the claim cites, like S1; empty if none")
    reason: str = Field(description="Why the cited sources don't support it")


class SelfCheck(BaseModel):
    gaps: list[_Gap]


def _to_gap(g: _Gap, sources: list[Source], sub_questions: list[str], question: str) -> Gap:
    """Keep only real source IDs, and fall back if the model's sub-question isn't in the plan:
    first to the sub-question of the first cited source, then to the main question."""
    by_id = {s["id"]: s for s in sources}
    source_ids = [i for i in g.source_ids if i in by_id]
    sub_question = g.sub_question
    if sub_question not in sub_questions:
        sub_question = by_id[source_ids[0]]["sub_question"] if source_ids else question
    return Gap(sub_question=sub_question, claim=g.claim, source_ids=source_ids, reason=g.reason)


async def self_check(state: ResearchState) -> Command[Literal["research_one", "approve_report"]]:
    """Find unsupported claims and re-research them, up to MAX_RESEARCH_LOOPS times.

    Once the cap is reached, the draft goes to human review with the gaps left in state.
    """
    sources = state.get("sources", [])
    sub_questions = state.get("sub_questions", [])
    prompt = SELF_CHECK_PROMPT.format(
        sub_questions="\n".join(f"- {q}" for q in sub_questions),
        draft=state.get("draft", ""),
        sources=format_sources(sources),
    )
    result = await get_model("planner").with_structured_output(SelfCheck).ainvoke(prompt)
    gaps = [_to_gap(g, sources, sub_questions, state["question"]) for g in result.gaps]

    loops = state.get("research_loops", 0)
    if gaps and loops < MAX_RESEARCH_LOOPS:
        return Command(
            update={"gaps": gaps, "research_loops": loops + 1}, goto=gap_tasks(gaps, sources)
        )
    return Command(update={"gaps": gaps}, goto="approve_report")


def approve_report(state: ResearchState) -> Command[Literal["write", "save_report"]]:
    """Pause for the human to review the draft.

    Interrupt payload: {"type": "approve_report", "draft": str,
                        "sources": [{"id", "url", "title"}],
                        "gaps": [{"sub_question", "claim", "source_ids", "reason"}]}
    Resume with: {"approved": bool, "feedback"?: str}
    """
    if state.get("auto_approve"):
        decision = {"approved": True}
    else:
        decision = interrupt(
            {
                "type": "approve_report",
                "draft": state.get("draft", ""),
                "sources": [
                    {"id": s["id"], "url": s["url"], "title": s["title"]}
                    for s in state.get("sources", [])
                ],
                "gaps": state.get("gaps", []),
            }
        )

    if decision.get("approved"):
        return Command(update={"report_feedback": ""}, goto="save_report")
    return Command(
        update={
            "report_feedback": decision.get("feedback", ""),
            "revision_loops": state.get("revision_loops", 0) + 1,
        },
        goto="write",
    )


def _render_report(state: ResearchState) -> str:
    """The approved report as markdown: the draft, then its sources, unresolved gaps, and
    run details. Source page text is left out; it stays in the checkpoint."""
    parts = [f"# {state['question']}", state.get("draft", "").strip()]

    if sources := state.get("sources", []):
        lines = [f"- [{s['id']}] [{s['title']}]({s['url']})" for s in sources]
        parts.append("## Sources\n\n" + "\n".join(lines))

    if gaps := state.get("gaps", []):
        lines = [
            f'- "{g["claim"]}" [{", ".join(g["source_ids"]) or "no citation"}]: {g["reason"]}'
            for g in gaps
        ]
        parts.append("## Unresolved gaps\n\n" + "\n".join(lines))

    sub_questions = "\n".join(f"- {q}" for q in state.get("sub_questions", []))
    parts.append(
        "## Run details\n\n"
        f"Sub-questions:\n\n{sub_questions}\n\n"
        f"- Research loops: {state.get('research_loops', 0)}\n"
        f"- Revision loops: {state.get('revision_loops', 0)}"
    )
    return "\n\n".join(parts) + "\n"


def save_report(state: ResearchState, config: RunnableConfig) -> dict:
    """Write the approved report to `results/<thread_id>.md`.

    Named by thread ID, so rerunning this node after a crash overwrites the same file.
    Runs without a thread ID get a timestamped name instead.
    """
    thread_id = config.get("configurable", {}).get("thread_id")
    name = re.sub(r"[^\w-]", "_", str(thread_id)) if thread_id else None
    name = name or datetime.now(UTC).strftime("report-%Y%m%dT%H%M%S%fZ")

    settings.results_dir.mkdir(parents=True, exist_ok=True)
    path = settings.results_dir / f"{name}.md"
    path.write_text(_render_report(state), encoding="utf-8")
    logger.info("saved report to %s", path)
    return {}
