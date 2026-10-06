"""Langfuse tracing for graph runs.

Each `ainvoke` (the first call and every resume after a human approval) is one trace
named `research-run`. All traces for a thread share `session_id = thread_id`, so the
Sessions view shows a whole run, approvals included. `build_graph` stays untraced, so
tests and other callers export nothing unless they go through `invoke_traced`.
"""

from functools import cache
from typing import Any

from langchain_core.runnables import RunnableConfig
from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from research_agent.config import settings

TRACE_NAME = "research-run"


def tracing_enabled() -> bool:
    return bool(settings.langfuse_public_key and settings.langfuse_secret_key)


@cache
def get_langfuse() -> Langfuse:
    """The Langfuse client, built from `settings` because `.env` never reaches os.environ."""
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_host,
        environment=settings.langfuse_tracing_environment,
    )


def _run_input(graph_input: dict | Command, state: dict) -> dict:
    """What a reviewer needs to read the trace: the question, plus the human's decision
    when this call resumes an approval."""
    if isinstance(graph_input, Command):
        return {"question": state.get("question"), "resume": graph_input.resume}
    return {"question": graph_input["question"]}


def _run_output(result: dict) -> dict:
    """The approval the run is waiting on, or the final report. Source page text is left
    out; it is on the `research_one` observations."""
    if interrupts := result.get("__interrupt__"):
        return {"awaiting": interrupts[0].value}
    return {
        "draft": result.get("draft", ""),
        "sources": [{"id": s["id"], "url": s["url"]} for s in result.get("sources", [])],
        "gaps": result.get("gaps", []),
    }


async def invoke_traced(
    graph: CompiledStateGraph,
    graph_input: dict | Command,
    config: RunnableConfig,
    *,
    entrypoint: str,
) -> dict[str, Any]:
    """Run `graph.ainvoke` as one Langfuse trace in the thread's session.

    `entrypoint` (cli, api, eval) becomes a tag, so dashboards can split traffic by source.
    Without Langfuse keys this is a plain `ainvoke`, so the agent still runs untraced.
    """
    if not tracing_enabled():
        return await graph.ainvoke(graph_input, config)

    thread_id = str(config["configurable"]["thread_id"])
    langfuse = get_langfuse()
    resume = isinstance(graph_input, Command)
    state = (await graph.aget_state(config)).values if resume else graph_input

    with langfuse.start_as_current_observation(
        name=TRACE_NAME,
        as_type="agent",
        input=_run_input(graph_input, state),
        metadata={
            "thread_id": thread_id,
            "resume": resume,
            "auto_approve": bool(state.get("auto_approve")),
        },
    ) as root:
        with propagate_attributes(trace_name=TRACE_NAME, session_id=thread_id, tags=[entrypoint]):
            handler = CallbackHandler(public_key=settings.langfuse_public_key)
            callbacks = [*(config.get("callbacks") or []), handler]
            run_config = {**config, "callbacks": callbacks, "run_name": "research-graph"}
            result = await graph.ainvoke(graph_input, run_config)
        root.update(output=_run_output(result))
    return result
