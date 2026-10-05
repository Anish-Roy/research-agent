"""research_one and the fan-out helpers that send one task per sub-question or gap."""

import asyncio
import logging

from langchain_core.tools import BaseTool
from langgraph.types import Send

from research_agent.models import get_model
from research_agent.state import FoundSource, Gap, ResearchTask, Source
from research_agent.tools import get_tavily_tools

logger = logging.getLogger(__name__)

RESULTS_PER_TASK = 3
MAX_CHARS_PER_SOURCE = 2000

QUERY_PROMPT = """Write one web search query to answer the research question below.
Return only the query, with no quotes or explanation.

Question: {sub_question}"""

GAP_QUERY_PROMPT = """While answering a research sub-question, a draft report made a claim
that its cited sources don't support.

Sub-question: {sub_question}
Claim: {claim}
Cited sources: {cited}
Why it failed: {reason}

Write one web search query to find a different source that confirms or corrects the claim.
Return only the query, with no quotes or explanation."""


def question_tasks(sub_questions: list[str]) -> list[Send]:
    return [Send("research_one", ResearchTask(sub_question=q)) for q in sub_questions]


def gap_tasks(gaps: list[Gap], sources: list[Source]) -> list[Send]:
    # research_one only sees its task, so resolve cited IDs to URLs here.
    urls = {s["id"]: s["url"] for s in sources}
    return [
        Send(
            "research_one",
            ResearchTask(
                sub_question=g["sub_question"],
                gap=g,
                cited_urls=[urls[i] for i in g["source_ids"] if i in urls],
            ),
        )
        for g in gaps
    ]


_tools: dict[str, BaseTool] | None = None
_tools_lock = asyncio.Lock()


async def _get_tools() -> dict[str, BaseTool]:
    """Load the Tavily tools once and share them across research tasks."""
    global _tools
    async with _tools_lock:
        if _tools is None:
            tools = {t.name: t for t in await get_tavily_tools()}
            missing = {"tavily_search", "tavily_extract"} - tools.keys()
            if missing:
                raise RuntimeError(f"Tavily tools not found: {sorted(missing)}")
            _tools = tools
    return _tools


async def _call(tool: BaseTool, args: dict) -> dict | None:
    """Call an MCP tool and return its structured result, or None if the call failed."""
    msg = await tool.ainvoke(
        {"type": "tool_call", "id": tool.name, "name": tool.name, "args": args}
    )
    if msg.status == "error":
        logger.warning("%s failed: %s", tool.name, str(msg.content)[:300])
        return None
    return (msg.artifact or {}).get("structured_content")


async def _search_query(task: ResearchTask) -> str:
    if gap := task.get("gap"):
        prompt = GAP_QUERY_PROMPT.format(
            sub_question=task["sub_question"],
            claim=gap["claim"],
            cited=", ".join(task.get("cited_urls", [])) or "none",
            reason=gap["reason"],
        )
    else:
        prompt = QUERY_PROMPT.format(sub_question=task["sub_question"])
    reply = await get_model("planner").ainvoke(prompt)
    return reply.text.strip().strip('"') or task["sub_question"]


async def research_one(task: ResearchTask) -> dict:
    """Search, extract, and trim sources for one sub-question or gap.

    Runs as a parallel `Send` task, so it writes only `sources`. A failed extract
    falls back to the search snippet; a failed search returns no sources.
    """
    tools = await _get_tools()
    query = await _search_query(task)

    search = await _call(tools["tavily_search"], {"query": query, "max_results": RESULTS_PER_TASK})
    # The DEFAULT_PARAMETERS header overrides max_results, so slice here.
    results = (search or {}).get("results", [])[:RESULTS_PER_TASK]
    if not results:
        logger.warning("no search results for %r", query)
        return {"sources": []}

    extract = await _call(
        tools["tavily_extract"],
        {"urls": [r["url"] for r in results], "query": task["sub_question"], "format": "text"},
    )
    pages = {r["url"]: r.get("raw_content") or "" for r in (extract or {}).get("results", [])}

    sources = [
        FoundSource(
            url=r["url"],
            title=r.get("title") or r["url"],
            content=(pages.get(r["url"]) or r.get("content") or "")[:MAX_CHARS_PER_SOURCE],
            sub_question=task["sub_question"],
        )
        for r in results
    ]
    return {"sources": [s for s in sources if s["content"]]}
