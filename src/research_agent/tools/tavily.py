import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable, Iterable

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest, MCPToolCallResult
from langchain_mcp_adapters.sessions import StreamableHttpConnection
from mcp.types import CallToolResult, TextContent

from research_agent.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TOOLS = ("tavily_search", "tavily_extract")

# Tavily errors worth retrying: rate limits and server-side failures.
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRIES = 5
BASE_DELAY = 2.0  # seconds; doubles each retry, with jitter


def tavily_connection() -> StreamableHttpConnection:
    if not settings.tavily_api_key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    return {
        "transport": "streamable_http",
        "url": settings.tavily_mcp_url,
        "headers": {
            "Authorization": f"Bearer {settings.tavily_api_key}",
            "DEFAULT_PARAMETERS": json.dumps(
                {"include_images": False, "search_depth": "advanced", "max_results": 10}
            ),
        },
    }


def _error_status(result: CallToolResult) -> int | None:
    """The status of a Tavily error body, or None if the result is not an error.

    Tavily reports API failures (rate limits, bad keys) as an ordinary result whose
    text is a JSON object with an `error` key. Returns 0 if the body has no status.
    """
    for block in result.content:
        if isinstance(block, TextContent):
            try:
                body = json.loads(block.text)
            except ValueError:
                continue
            if isinstance(body, dict) and "error" in body:
                status = body.get("status")
                return status if isinstance(status, int) else 0
    return None


async def retry_tavily_errors(
    request: MCPToolCallRequest,
    handler: Callable[[MCPToolCallRequest], Awaitable[MCPToolCallResult]],
) -> MCPToolCallResult:
    """Retry rate limits and server errors with backoff, then flag what still fails.

    A final failure becomes an MCP error, so the tool call ends with status "error":
    callers see it, and Langfuse marks the tool observation ERROR. Retries happen inside
    the one tool call, so a call that recovers shows as a single successful observation.
    """
    for attempt in range(MAX_RETRIES + 1):
        result = await handler(request)
        if not isinstance(result, CallToolResult) or result.isError:
            return result
        status = _error_status(result)
        if status is None:
            return result
        if status not in RETRY_STATUSES or attempt == MAX_RETRIES:
            return result.model_copy(update={"isError": True})
        delay = BASE_DELAY * 2**attempt * random.uniform(0.75, 1.25)
        logger.warning(
            "%s returned %s, retry %d/%d in %.1fs",
            request.name,
            status,
            attempt + 1,
            MAX_RETRIES,
            delay,
        )
        await asyncio.sleep(delay)
    raise AssertionError("unreachable")


async def get_tavily_tools(names: Iterable[str] = DEFAULT_TOOLS) -> list[BaseTool]:
    client = MultiServerMCPClient(
        {"tavily": tavily_connection()}, tool_interceptors=[retry_tavily_errors]
    )
    all_tools = await client.get_tools()

    return [tool for tool in all_tools if tool.name in names]
