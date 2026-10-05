import json
from collections.abc import Iterable

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StreamableHttpConnection

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


async def get_tavily_tools(names: Iterable[str] = DEFAULT_TOOLS) -> list[BaseTool]:
    client = MultiServerMCPClient({"tavily": tavily_connection()})
    all_tools = await client.get_tools()

    return [tool for tool in all_tools if tool.name in names]
