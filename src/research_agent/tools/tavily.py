import json
from collections.abc import Awaitable, Callable, Iterable

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest, MCPToolCallResult
from langchain_mcp_adapters.sessions import StreamableHttpConnection
from mcp.types import CallToolResult, TextContent

from research_agent.config import settings

DEFAULT_TOOLS = ("tavily_search", "tavily_extract")


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


def _is_error_body(result: CallToolResult) -> bool:
    """Tavily reports API failures (rate limits, bad keys) as an ordinary result whose
    text is a JSON object with an `error` key."""
    for block in result.content:
        if isinstance(block, TextContent):
            try:
                body = json.loads(block.text)
            except ValueError:
                continue
            if isinstance(body, dict) and "error" in body:
                return True
    return False


async def flag_tavily_errors(
    request: MCPToolCallRequest,
    handler: Callable[[MCPToolCallRequest], Awaitable[MCPToolCallResult]],
) -> MCPToolCallResult:
    """Turn Tavily error bodies into MCP errors, so the tool call ends with status
    "error": callers see the failure and Langfuse marks the tool observation ERROR."""
    result = await handler(request)
    if isinstance(result, CallToolResult) and not result.isError and _is_error_body(result):
        return result.model_copy(update={"isError": True})
    return result


async def get_tavily_tools(names: Iterable[str] = DEFAULT_TOOLS) -> list[BaseTool]:
    client = MultiServerMCPClient(
        {"tavily": tavily_connection()}, tool_interceptors=[flag_tavily_errors]
    )
    all_tools = await client.get_tools()

    return [tool for tool in all_tools if tool.name in names]
