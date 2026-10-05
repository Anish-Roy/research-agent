"""Graph wiring: nodes and the static edges between them.

Nodes that pick the next step (`approve_plan`, `check_citations`, `self_check`,
`approve_report`) return a `Command`, so they have no outgoing edges here. The fan-out
in PROJECT.md is not a separate conditional edge: `approve_plan` and `self_check` return
`Command(goto=[Send("research_one", ...), ...])` themselves. The static edge from
`research_one` to `write` runs `write` once, after every parallel task has finished.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from research_agent.config import settings
from research_agent.nodes import (
    approve_plan,
    approve_report,
    check_citations,
    plan,
    research_one,
    save_report,
    self_check,
    write,
)
from research_agent.state import ResearchState


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    """Compile the research graph.

    The approval nodes call `interrupt`, which needs a checkpointer and a `thread_id` in
    the run config. A run that sets `auto_approve: True` in its input state never
    interrupts, so it can run without one.
    """
    builder = StateGraph(ResearchState)

    builder.add_node("plan", plan)
    builder.add_node("approve_plan", approve_plan)
    builder.add_node("research_one", research_one)
    builder.add_node("write", write)
    builder.add_node("check_citations", check_citations)
    builder.add_node("self_check", self_check)
    builder.add_node("approve_report", approve_report)
    builder.add_node("save_report", save_report)

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "approve_plan")
    builder.add_edge("research_one", "write")
    builder.add_edge("write", "check_citations")
    builder.add_edge("save_report", END)

    return builder.compile(checkpointer=checkpointer)


@asynccontextmanager
async def postgres_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """Open a checkpointer on `DATABASE_URL`, creating its tables if they don't exist.

    Use one per process: `async with postgres_checkpointer() as saver:`.
    """
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as saver:
        await saver.setup()
        yield saver
